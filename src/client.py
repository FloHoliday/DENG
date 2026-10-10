"""OpenF1 HTTP client: rate limited, retries transient errors, returns everything else for classification."""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from pyrate_limiter import Duration, Limiter, Rate
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from config import Settings

USER_AGENT = "deng-f1-pipeline/0.1 (HSLU Data Engineering student project)"
CLIENT_VERSION = "0.1.0"
MAX_RETRY_AFTER_SECONDS = 120
TRANSIENT_STATUS = {429, 500, 502, 503, 504}

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchResult:
    url: str
    params: dict
    status_code: int | None  # None when no response arrived (timeout/connection error)
    content: bytes  # exact response body, stored unchanged in the raw zone
    data: Any  # parsed JSON, None if the body is not valid JSON
    elapsed_ms: int
    attempts: int
    error: str | None = None  # set when transient errors persisted after all retries


class TransientError(Exception):
    """A failure worth retrying: 429, 5xx, timeout or connection error."""

    def __init__(
        self,
        reason: str,
        response: httpx.Response | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(reason)
        self.response = response
        self.retry_after = retry_after


def parse_retry_after(value: str | None) -> float | None:
    """Seconds from a Retry-After header, capped; the HTTP-date form is ignored (backoff is used instead)."""
    try:
        return min(float(value), MAX_RETRY_AFTER_SECONDS) if value else None
    except ValueError:
        return None


class OpenF1Client:
    def __init__(
        self,
        settings: Settings,
        *,
        limiter: Limiter | None = None,
        sleep=time.sleep,
    ):
        self._http = httpx.Client(
            base_url=settings.openf1_base_url,
            timeout=httpx.Timeout(settings.http_timeout_seconds, connect=5.0),
            headers={"User-Agent": USER_AGENT},
            trust_env=True,
        )
        # One limiter per process, applied to every attempt: both API limits (per second and per minute) hold.
        self._limiter = limiter or Limiter(
            [
                Rate(settings.rate_limit_per_second, Duration.SECOND),
                Rate(settings.rate_limit_per_minute, Duration.MINUTE),
            ]
        )
        self._max_attempts = settings.max_retry_attempts
        self._sleep = sleep
        self._backoff = wait_exponential_jitter(multiplier=2, max=60)
        self.requests_made = 0  # all HTTP attempts of this client, for --max-requests

    def close(self) -> None:
        self._http.close()

    def _wait(self, retry_state: RetryCallState) -> float:
        exc = retry_state.outcome.exception()
        if isinstance(exc, TransientError) and exc.retry_after is not None:
            return exc.retry_after
        return self._backoff(retry_state)

    def _send(self, endpoint: str, params: dict) -> httpx.Response:
        self._limiter.try_acquire("openf1")
        self.requests_made += 1
        try:
            response = self._http.get(f"/{endpoint}", params=params)
        except httpx.TransportError as exc:  # timeouts and connection errors
            raise TransientError(f"{type(exc).__name__}: {exc}") from exc
        if response.status_code in TRANSIENT_STATUS:
            raise TransientError(
                f"HTTP {response.status_code}",
                response,
                parse_retry_after(response.headers.get("Retry-After")),
            )
        return response

    def get(self, endpoint: str, params: dict) -> FetchResult:
        start = time.monotonic()
        attempts = 0

        def log_retry(retry_state: RetryCallState) -> None:
            log.warning(
                "%s %s: %s, retry %d in %.1fs",
                endpoint,
                params,
                retry_state.outcome.exception(),
                retry_state.attempt_number,
                retry_state.next_action.sleep,
            )

        retrying = Retrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=self._wait,
            retry=retry_if_exception_type(TransientError),
            sleep=self._sleep,
            before_sleep=log_retry,
            reraise=True,
        )
        error = None
        try:
            for attempt in retrying:
                with attempt:
                    attempts += 1
                    response = self._send(endpoint, params)
        except TransientError as exc:
            response, error = exc.response, f"{exc} after {attempts} attempts"

        content = response.content if response is not None else b""
        try:
            data = json.loads(content) if content else None
        except ValueError:
            data = None
        return FetchResult(
            url=str(response.url) if response is not None else f"/{endpoint}",
            params=params,
            status_code=response.status_code if response is not None else None,
            content=content,
            data=data,
            elapsed_ms=round((time.monotonic() - start) * 1000),
            attempts=attempts,
            error=error,
        )
