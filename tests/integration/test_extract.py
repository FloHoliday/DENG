import uuid
from datetime import UTC, datetime

import httpx
import pytest
import respx

import ingest
import state
from client import OpenF1Client
from discovery import Filters
from fetch import Context, extract

pytestmark = pytest.mark.db

NOW = datetime(
    2026, 1, 15, tzinfo=UTC
)  # long after the race: outside the settling window
SESSIONS = [
    {
        "session_key": 9835,
        "session_name": "Qualifying",
        "session_type": "Qualifying",
        "meeting_key": 1276,
        "year": 2025,
        "date_start": "2025-12-06T14:00:00+00:00",
        "date_end": "2025-12-06T15:00:00+00:00",
        "is_cancelled": False,
    },
    {
        "session_key": 9839,
        "session_name": "Race",
        "session_type": "Race",
        "meeting_key": 1276,
        "year": 2025,
        "date_start": "2025-12-07T13:00:00+00:00",
        "date_end": "2025-12-07T15:00:00+00:00",
        "is_cancelled": False,
    },
]
NO_RESULTS = httpx.Response(404, json={"detail": "No results found."})


class FakeApi:
    """Answers like OpenF1 for one race weekend; `drivers_status` lets a test break the drivers call."""

    def __init__(self):
        self.drivers_status = 200
        self.calls = []

    def __call__(self, request, endpoint):
        params = dict(request.url.params)
        self.calls.append((endpoint, params))
        if endpoint == "meetings":
            return httpx.Response(
                200, json=[{"meeting_key": 1276, "year": 2025, "is_cancelled": False}]
            )
        if endpoint == "sessions":
            return httpx.Response(200, json=SESSIONS)
        if endpoint == "drivers":
            return httpx.Response(
                self.drivers_status, json=[{"driver_number": 1}, {"driver_number": 44}]
            )
        if endpoint == "starting_grid":
            # Only the qualifying key has a grid (docs/api-notes.md).
            if params["session_key"] != "9835":
                return NO_RESULTS
            return httpx.Response(
                200, json=[{"position": 1, "driver_number": 1, "session_key": 9835}]
            )
        if endpoint == "car_data":
            return httpx.Response(
                200,
                json=[{"driver_number": int(params["driver_number"]), "speed": 300}],
            )
        if endpoint == "pit":
            return NO_RESULTS
        return httpx.Response(200, json=[{"session_key": 9839, "driver_number": 1}])


class NoLimit:
    def try_acquire(self, name):
        pass


@pytest.fixture
def api(db_settings):
    fake = FakeApi()
    with respx.mock(base_url=db_settings.openf1_base_url) as mock:
        mock.get(path__regex=r"/(?P<endpoint>\w+)$").mock(side_effect=fake)
        yield fake


def context(db_settings, conn, store):
    client = OpenF1Client(db_settings, limiter=NoLimit(), sleep=lambda s: None)
    return Context(db_settings, conn, store, client, uuid.uuid4(), NOW)


def statuses(conn):
    return state.unit_statuses(conn, 9839)


def test_extract_then_load(db_settings, conn, store, api):
    ctx = context(db_settings, conn, store)
    extract(ctx, Filters())
    units = statuses(conn)
    assert (
        units[("car_data", "driver=1")] == "done"
        and units[("car_data", "driver=44")] == "done"
    )
    assert units[("pit", "all")] == "empty"
    assert units[("starting_grid", "all")] == "done"
    assert ("starting_grid", {"session_key": "9835"}) in api.calls

    counts = ingest.load(conn, store, ctx.run_id)
    assert counts["load_failed"] == 0
    assert conn.execute("SELECT count(*) FROM raw.car_data").fetchone()[0] == 2
    assert (
        conn.execute("SELECT session_key FROM raw.starting_grid").fetchone()[0] == 9835
    )

    # Rerun: only the metadata refresh hits the API, and nothing is reloaded.
    api.calls.clear()
    extract(context(db_settings, conn, store), Filters())
    assert {endpoint for endpoint, _ in api.calls} == {"meetings", "sessions"}
    assert ingest.load(conn, store, ctx.run_id)["loaded"] == 0


def test_no_car_data_without_drivers(db_settings, conn, store, api):
    api.drivers_status = 400
    extract(context(db_settings, conn, store), Filters())
    units = statuses(conn)
    assert units[("drivers", "all")] == "failed"
    assert not [k for k in units if k[0] == "car_data"]
    # The 9 complete race partitions load; drivers (failed) is skipped, metadata was loaded by extract.
    assert ingest.load(conn, store, uuid.uuid4())["loaded"] == 9
    assert conn.execute("SELECT count(*) FROM raw.drivers").fetchone()[0] == 0
