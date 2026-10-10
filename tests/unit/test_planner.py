from datetime import UTC, datetime, timedelta

import pytest

from fetch import car_data_units, in_settling_window, race_units, units_to_run
from raw_store import RawStore

END = datetime(2025, 12, 7, 15, tzinfo=UTC)
RACE = {"session_key": 9839, "meeting_key": 1276, "year": 2025, "date_end": END}
QUALI = {"session_key": 9835, "meeting_key": 1276, "session_name": "Qualifying"}


@pytest.fixture
def store(settings):
    return RawStore(settings.raw_uri)


@pytest.fixture
def units(store):
    return race_units(store, RACE, [QUALI], ())


def ids(units):
    return [(u.endpoint, u.chunk_key) for u in units]


def test_race_units_drivers_first_and_grid_on_qualifying(units):
    assert units[0].endpoint == "drivers"
    assert len(units) == 10
    grid = next(u for u in units if u.endpoint == "starting_grid")
    assert grid.params == {"session_key": 9835} and grid.queried_session_key == 9835
    assert "session_key=9839" in grid.raw_dir  # path always uses the race key


def test_grid_without_qualifying_has_nothing_to_query(store):
    grid = race_units(store, RACE, [], ("starting_grid",))
    assert [u.params for u in grid] == [None]


def test_endpoint_filter(store):
    assert ids(race_units(store, RACE, [QUALI], ("laps", "pit"))) == [
        ("laps", "all"),
        ("pit", "all"),
    ]


def test_planning_is_idempotent(units):
    first = units_to_run(units, {}, reset=False)
    assert first == units
    assert units_to_run(units, {}, reset=False) == first  # planning twice: same units
    done = {(u.endpoint, u.chunk_key): "done" for u in units}
    assert units_to_run(units, done, reset=False) == []


def test_failed_deferred_pending_are_replanned_but_done_empty_not(units):
    statuses = dict.fromkeys(ids(units), "done")
    statuses[("pit", "all")] = "empty"
    statuses[("laps", "all")] = "failed"
    statuses[("weather", "all")] = "deferred"
    statuses[("stints", "all")] = "pending"
    assert sorted(ids(units_to_run(units, statuses, reset=False))) == [
        ("laps", "all"),
        ("stints", "all"),
        ("weather", "all"),
    ]


def test_force_resets_completed_units(units):
    done = dict.fromkeys(ids(units), "done")
    assert units_to_run(units, done, reset=True) == units


def test_settling_window():
    assert in_settling_window(RACE, END + timedelta(days=3), 3)
    assert not in_settling_window(RACE, END + timedelta(days=3, seconds=1), 3)


def test_car_data_one_unit_per_driver(store):
    drivers = [{"driver_number": 44}, {"driver_number": 1}, {"driver_number": 44}]
    units = car_data_units(store, RACE, drivers)
    assert ids(units) == [("car_data", "driver=1"), ("car_data", "driver=44")]
    assert units[1].params == {"session_key": 9839, "driver_number": 44}
    assert units[1].raw_dir.endswith("session_key=9839/driver_number=44")
