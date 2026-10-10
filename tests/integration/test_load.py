import json
import uuid

import pytest

import ingest
import state

pytestmark = pytest.mark.db

KEY = 9839
RUN = uuid.uuid4()


def lap(n, **extra):
    return {
        "session_key": KEY,
        "driver_number": 1,
        "lap_number": n,
        "lap_duration": 90.5,
        "segments_sector_1": [2048, 2049],
        "date_start": "2025-12-07T13:03:00+00:00",
        **extra,
    }


def extracted(conn, store, records, record_count=None):
    """Put a laps file in the raw zone and mark its unit done, as the extract step does."""
    unit = store.unit_dir("laps", 2025, 1276, KEY)
    count = len(records) if record_count is None else record_count
    manifest = store.write(unit, json.dumps(records).encode(), {"record_count": count})
    state.set_pending(conn, "laps", KEY, "all")
    state.record_result(
        conn,
        "laps",
        KEY,
        "all",
        status="done",
        attempts=1,
        http_status=200,
        last_error=None,
        run_id=RUN,
        record_count=count,
        sha256=manifest["sha256"],
        raw_path=unit,
    )


def rows(conn):
    return conn.execute(
        "SELECT count(*) FROM raw.laps WHERE _race_session_key = %s", (KEY,)
    ).fetchone()[0]


def loaded_at(conn):
    return conn.execute(
        "SELECT loaded_at FROM meta.load_state WHERE endpoint = 'laps'"
    ).fetchone()[0]


def test_second_load_is_noop(conn, store):
    extracted(conn, store, [lap(1), lap(2)])
    assert ingest.load_partition(conn, store, "laps", KEY, RUN) == 2
    first = loaded_at(conn)
    assert ingest.load_partition(conn, store, "laps", KEY, RUN) is None
    assert rows(conn) == 2 and loaded_at(conn) == first
    # typed columns
    assert conn.execute(
        "SELECT segments_sector_1, lap_duration FROM raw.laps LIMIT 1"
    ).fetchone() == ([2048, 2049], 90.5)


def test_changed_file_replaces_partition(conn, store):
    extracted(conn, store, [lap(1), lap(2)])
    ingest.load_partition(conn, store, "laps", KEY, RUN)
    extracted(conn, store, [lap(1), lap(2), lap(3)])
    assert ingest.load_partition(conn, store, "laps", KEY, RUN) == 3
    assert rows(conn) == 3


def test_reconciliation_mismatch_rolls_back(conn, store):
    extracted(conn, store, [lap(1), lap(2)])
    ingest.load_partition(conn, store, "laps", KEY, RUN)
    before = loaded_at(conn)
    extracted(conn, store, [lap(1), lap(2), lap(3)], record_count=5)
    with pytest.raises(ingest.ReconciliationError):
        ingest.load_partition(conn, store, "laps", KEY, RUN)
    assert rows(conn) == 2 and loaded_at(conn) == before


def test_tampered_file_is_rejected(conn, store):
    extracted(conn, store, [lap(1)])
    store.write(
        store.unit_dir("laps", 2025, 1276, KEY), b"[]", {"record_count": 0}
    )  # sha no longer matches state
    with pytest.raises(ingest.ReconciliationError):
        ingest.load_partition(conn, store, "laps", KEY, RUN)
    assert rows(conn) == 0


def test_unknown_field_goes_to_extra(conn, store):
    extracted(conn, store, [lap(1, new_field="x")])
    ingest.load_partition(conn, store, "laps", KEY, RUN)
    assert conn.execute("SELECT _extra FROM raw.laps").fetchone()[0] == {
        "new_field": "x"
    }


def test_partition_with_unfinished_unit_is_not_loaded(conn, store):
    extracted(conn, store, [lap(1)])
    state.set_pending(conn, "laps", KEY, "all")
    assert ingest.load_partition(conn, store, "laps", KEY, RUN) is None
    assert rows(conn) == 0
