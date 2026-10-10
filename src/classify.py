"""Turn an API response into the status of an extract unit (briefing §6.4)."""

from datetime import datetime, timedelta

from client import FetchResult

# OpenF1 answers an empty result with 404 and this body instead of 200 [] (docs/api-notes.md).
EMPTY_DETAIL = "No results found."


def is_empty(result: FetchResult) -> bool:
    if result.status_code == 200:
        return result.data == []
    return (
        result.status_code == 404
        and isinstance(result.data, dict)
        and result.data.get("detail") == EMPTY_DETAIL
    )


def record_count(result: FetchResult) -> int:
    return (
        len(result.data)
        if result.status_code == 200 and isinstance(result.data, list)
        else 0
    )


def classify(
    result: FetchResult,
    *,
    now: datetime,
    session_end: datetime | None,
    live: bool,
    settling_days: int,
) -> tuple[str, str | None]:
    """Return (status, error). session_end None means no settling window (metadata units)."""
    if result.error:
        return "failed", result.error
    if result.status_code in (401, 403):
        # Live sessions block the free API: expected while live, unexplained otherwise.
        if live:
            return "deferred", f"HTTP {result.status_code} during live window"
        return "failed", f"HTTP {result.status_code} outside any live window"
    if is_empty(result):
        if session_end is not None and now - session_end <= timedelta(
            days=settling_days
        ):
            return (
                "deferred",
                "empty within settling window, data may still be published",
            )
        return "empty", None
    if result.status_code == 200:
        if isinstance(result.data, list):
            return "done", None
        return "failed", "HTTP 200 but body is not a JSON list"
    return "failed", f"HTTP {result.status_code}: {result.content[:200]!r}"
