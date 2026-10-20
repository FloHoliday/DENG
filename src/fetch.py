"""Fetch step: fetch the raw OpenF1 data of all race weekends since a date and save it unchanged as JSON."""

import json
import re
import sys
import time
from datetime import UTC, date, datetime

import httpx
from pyrate_limiter import Duration, Limiter, Rate
from pyrate_limiter.extras.httpx_limiter import RateLimiterTransport
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from upath import UPath

BASE_URL = "https://api.openf1.org/v1"
# API limit: up to 3 requests/second & 30 requests/minute
RATE_LIMITS = [Rate(3, Duration.SECOND), Rate(30, Duration.MINUTE)]
# Errors that mark a single fetch as failed without aborting the whole run.
FETCH_ERRORS = (httpx.HTTPError, ValueError)

SESSION_ENDPOINTS = [
    "drivers",
    "laps",
    "stints",
    "pit",
    "position",
    "race_control",
    "session_result",
    "weather",
    "intervals",
]
# May legitimately be empty: a race without pit stops, a driver who didn't start (no
# car_data). Every other endpoint must return rows, otherwise the fetch counts as failed.
MAY_BE_EMPTY = {"pit", "car_data"}


def is_retryable(exc: BaseException) -> bool:
    """Timeouts, connection errors, 422 (OpenF1 overloaded), 429 and 5xx are worth retrying."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status in (422, 429) or status >= 500
    return isinstance(exc, httpx.TransportError)


def log_retry(state) -> None:
    exc = state.outcome.exception()
    error = (
        f"HTTP {exc.response.status_code}"
        if isinstance(exc, httpx.HTTPStatusError)
        else repr(exc)
    )
    _, endpoint, params = state.args
    print(
        f"{endpoint} {params}: {error}, retrying in {state.next_action.sleep:.0f}s",
        file=sys.stderr,
    )


class OpenF1Client:
    def __init__(self) -> None:
        self._http = httpx.Client(
            base_url=BASE_URL,
            timeout=60,
            transport=RateLimiterTransport(limiter=Limiter(RATE_LIMITS)),
        )

    @retry(
        retry=retry_if_exception(is_retryable),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2),
        before_sleep=log_retry,
        reraise=True,
    )
    def get(self, endpoint: str, params: dict) -> list[dict]:
        resp = self._http.get(endpoint, params=params)
        if resp.status_code == 404:
            return []
        if resp.status_code == 401:
            # During live F1 sessions the whole API requires an API key.
            sys.exit(f"OpenF1 access denied: {resp.json().get('detail', resp.text)}")
        resp.raise_for_status()
        return resp.json()


def find_meetings(client: OpenF1Client, since: date) -> list[dict]:
    """Non-cancelled meetings starting on or after `since`."""
    today = datetime.now(UTC).date()
    return client.get(
        "meetings",
        {"date_start>": str(since), "date_end<": str(today), "is_cancelled": False},
    )


def check_source(since: date) -> int:
    """Check that OpenF1 answers (no live-session lock) and list the race weekends to fetch."""
    meetings = find_meetings(OpenF1Client(), since)
    for meeting in meetings:
        print(
            f"{meeting['date_start'][:10]}  {meeting['meeting_name']} (meeting_key={meeting['meeting_key']})"
        )
    print(f"OpenF1 is reachable: {len(meetings)} finished race weekends since {since}")
    return len(meetings)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def write_json(path: UPath, data: list | dict) -> None:
    """Write to a temporary file first, so an interrupted run never leaves a truncated file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)


def fetch_to_file(
    client: OpenF1Client, path: UPath, force: bool, endpoint: str, **params
) -> int:
    """Fetch one endpoint into `path` and return its row count."""
    if path.exists() and not force:
        rows = len(json.loads(path.read_text(encoding="utf-8")))
        print(f"skip  {path.name:<40} {rows:6d} rows (exists)")
        return rows
    start = time.monotonic()
    data = client.get(endpoint, params)
    if not data and endpoint not in MAY_BE_EMPTY:
        raise ValueError(f"{endpoint}: no data for {params}")
    write_json(path, data)
    print(
        f"fetch {path.name:<40} {len(data):6d} rows in {time.monotonic() - start:.1f}s"
    )
    return len(data)


def fetch_car_data(
    client: OpenF1Client, session_dir: UPath, session_key: int, force: bool
) -> dict[str, int]:
    drivers = json.loads((session_dir / "drivers.json").read_text(encoding="utf-8"))
    counts = {}
    for driver_number in sorted({d["driver_number"] for d in drivers}):
        name = f"car_data/driver_{driver_number}"
        counts[name] = fetch_to_file(
            client,
            session_dir / f"{name}.json",
            force,
            "car_data",
            session_key=session_key,
            driver_number=driver_number,
        )
    return counts


def fetch_session(
    client: OpenF1Client,
    session: dict,
    meeting_dir: UPath,
    force: bool,
) -> bool:
    session_key = session["session_key"]
    session_dir = meeting_dir / f"{session_key}_{slug(session['session_name'])}"
    print(f"== {session['session_name']} (session_key={session_key}) -> {session_dir}")
    # Keep the marker unchanged so the store step doesn't reload the session.
    if (session_dir / "_SUCCESS").exists() and not force:
        print("skip  session (complete)")
        return True
    # A forced re-fetch removes the marker first: if it fails partway, the session must
    # not look complete with a mix of old and new files.
    (session_dir / "_SUCCESS").unlink(missing_ok=True)

    counts: dict[str, int] = {}
    failed = False
    for endpoint in SESSION_ENDPOINTS:
        try:
            counts[endpoint] = fetch_to_file(
                client,
                session_dir / f"{endpoint}.json",
                force,
                endpoint,
                session_key=session_key,
            )
        except FETCH_ERRORS as exc:
            print(f"FAILED {endpoint}: {exc}", file=sys.stderr)
            failed = True

    try:
        grid_sessions = client.get(
            "sessions",
            {"meeting_key": session["meeting_key"], "session_name": "Qualifying"},
        )
        if not grid_sessions:
            print("FAILED starting_grid: no qualifying session found", file=sys.stderr)
            failed = True
        else:
            counts["starting_grid"] = fetch_to_file(
                client,
                session_dir / "starting_grid.json",
                force,
                "starting_grid",
                session_key=grid_sessions[0]["session_key"],
            )
    except FETCH_ERRORS as exc:
        print(f"FAILED starting_grid: {exc}", file=sys.stderr)
        failed = True

    if "drivers" in counts:
        try:
            counts |= fetch_car_data(client, session_dir, session_key, force)
        except FETCH_ERRORS as exc:
            print(f"FAILED car_data: {exc}", file=sys.stderr)
            failed = True
    else:
        print("FAILED car_data: drivers list unavailable", file=sys.stderr)
        failed = True

    if failed:
        print(f"Session {session_key} incomplete, no _SUCCESS written", file=sys.stderr)
        return False
    write_json(
        session_dir / "_SUCCESS",
        {"completed_at": datetime.now(UTC).isoformat(), "row_counts": counts},
    )
    return True


def fetch_meeting(
    client: OpenF1Client,
    meeting: dict,
    raw_dir: UPath,
    force: bool,
) -> list[bool]:
    """Fetch the meeting metadata and the `selected` sessions; one result per session."""
    try:
        sessions = client.get(
            "sessions",
            {"meeting_key": meeting["meeting_key"], "session_name": "Race"},
        )
    except FETCH_ERRORS as exc:
        print(f"FAILED meeting {meeting['meeting_key']}: {exc}", file=sys.stderr)
        return [False]

    meeting_dir = (
        raw_dir
        / str(meeting["year"])
        / f"{meeting['meeting_key']}_{slug(meeting['location'])}"
    )
    print(
        f"Meeting: {meeting['year']} {meeting['meeting_name']} (meeting_key={meeting['meeting_key']})"
    )
    write_json(meeting_dir / "meeting.json", meeting)
    write_json(meeting_dir / "sessions.json", sessions)

    return [fetch_session(client, s, meeting_dir, force) for s in sessions]


def run(
    since: date,
    raw_dir: UPath,
    force: bool = False,
) -> int:
    """Fetch all race weekends since `since` into `raw_dir`; returns the number of failed sessions."""
    client = OpenF1Client()

    meetings = find_meetings(client, since)
    if not meetings:
        # Normal in weeks without a race: nothing to do is not a failure.
        print(f"No finished race weekend since {since}, nothing to fetch")
        return 0

    results = []
    for meeting in meetings:
        results += fetch_meeting(client, meeting, raw_dir, force)
    print(
        f"Fetched {results.count(True)} of {len(results)} sessions from {len(meetings)} meetings into {raw_dir}"
    )
    return results.count(False)
