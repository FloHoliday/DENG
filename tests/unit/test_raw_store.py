import gzip
import hashlib
import os

import pytest

import raw_store
from raw_store import RawStore

PAYLOAD = b'[{"driver_number": 1, "speed": 300}]'


@pytest.fixture
def store(settings):
    return RawStore(settings.raw_uri)


def test_paths_are_deterministic(store):
    race = store.unit_dir("car_data", 2025, 1276, 9839, 44)
    assert race == store.unit_dir("car_data", 2025, 1276, 9839, 44)
    assert race.endswith(
        "/openf1/v1/car_data/year=2025/meeting_key=1276/session_key=9839/driver_number=44"
    )
    assert store.unit_dir("laps", 2025, 1276, 9839).endswith(
        "/laps/year=2025/meeting_key=1276/session_key=9839"
    )
    assert store.unit_dir("sessions", 2025).endswith("/openf1/v1/sessions/year=2025")


def test_round_trip_and_manifest(store):
    unit = store.unit_dir("laps", 2025, 1276, 9839)
    written = store.write(unit, PAYLOAD, {"endpoint": "laps", "record_count": 1})
    assert store.read_payload(unit) == PAYLOAD
    assert store.read_records(unit) == [{"driver_number": 1, "speed": 300}]
    manifest = store.read_manifest(unit)
    assert manifest == written
    assert manifest["sha256"] == hashlib.sha256(PAYLOAD).hexdigest()
    assert manifest["bytes"] == len(PAYLOAD)
    assert manifest["endpoint"] == "laps" and manifest["fetched_at"]
    # Stored gzip-compressed, exact bytes inside.
    with open(f"{unit}/data.json.gz", "rb") as f:
        assert gzip.decompress(f.read()) == PAYLOAD


def test_empty_404_body_reads_as_no_records(store):
    unit = store.unit_dir("pit", 2025, 1276, 9839)
    store.write(unit, b'{"detail":"No results found."}', {"record_count": 0})
    assert store.read_records(unit) == []


def test_missing_manifest_is_none(store):
    assert store.read_manifest(store.unit_dir("laps", 2025, 1, 2)) is None


def test_failure_before_rename_leaves_no_file_and_no_manifest(store, monkeypatch):
    unit = store.unit_dir("laps", 2025, 1276, 9839)

    def crash(src, dst):
        raise OSError("disk gone")

    monkeypatch.setattr(raw_store.os, "replace", crash)
    with pytest.raises(OSError):
        store.write(unit, PAYLOAD, {"record_count": 1})
    assert os.listdir(unit) == []  # no data file, no manifest, no temp file


def test_rewrite_overwrites_same_path(store):
    unit = store.unit_dir("laps", 2025, 1276, 9839)
    store.write(unit, b"[]", {"record_count": 0})
    store.write(unit, PAYLOAD, {"record_count": 1})
    assert store.read_payload(unit) == PAYLOAD
    assert sorted(os.listdir(unit)) == ["_manifest.json", "data.json.gz"]
