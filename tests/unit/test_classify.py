import json
from datetime import UTC, datetime, timedelta

import pytest

from classify import classify, record_count
from client import FetchResult

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
OLD = NOW - timedelta(days=30)


def result(status, body=None, error=None):
    content = json.dumps(body).encode() if body is not None else b""
    return FetchResult(
        url="u",
        params={},
        status_code=status,
        content=content,
        data=body,
        elapsed_ms=1,
        attempts=1,
        error=error,
    )


def status_of(r, session_end=OLD, live=False):
    return classify(r, now=NOW, session_end=session_end, live=live, settling_days=3)[0]


def test_records_done():
    r = result(200, [{"a": 1}])
    assert status_of(r) == "done" and record_count(r) == 1


@pytest.mark.parametrize(
    "r", [result(200, []), result(404, {"detail": "No results found."})]
)
def test_empty_after_settling(r):
    assert status_of(r) == "empty" and record_count(r) == 0


@pytest.mark.parametrize(
    "r", [result(200, []), result(404, {"detail": "No results found."})]
)
def test_empty_within_settling_is_deferred(r):
    assert status_of(r, session_end=NOW - timedelta(days=1)) == "deferred"


def test_settling_boundary():
    r = result(200, [])
    assert status_of(r, session_end=NOW - timedelta(days=3)) == "deferred"
    assert status_of(r, session_end=NOW - timedelta(days=3, seconds=1)) == "empty"


def test_metadata_without_session_end_is_empty():
    assert status_of(result(200, []), session_end=None) == "empty"


@pytest.mark.parametrize("code", [401, 403])
def test_blackout(code):
    r = result(code, {"detail": "Live F1 session in progress"})
    assert status_of(r, live=True) == "deferred"
    assert status_of(r, live=False) == "failed"


def test_transient_after_retries_failed():
    status, error = classify(
        result(503, error="HTTP 503 after 6 attempts"),
        now=NOW,
        session_end=OLD,
        live=False,
        settling_days=3,
    )
    assert status == "failed" and "503" in error


@pytest.mark.parametrize(
    "r",
    [
        result(400, {"detail": "bad"}),
        result(422, {"detail": "too much"}),
        result(404, {"detail": "Not Found"}),
    ],
)
def test_other_4xx_failed(r):
    assert status_of(r) == "failed"


def test_200_not_a_list_failed():
    assert status_of(result(200, {"a": 1})) == "failed"
    assert status_of(result(200, None)) == "failed"  # invalid JSON parses to None
