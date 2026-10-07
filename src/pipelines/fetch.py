"""Fetch the OpenF1 data of all race weekends since a date into raw JSONL files."""

from datetime import UTC, date, datetime
from pathlib import Path

import dlt
from dlt.sources.rest_api import RESTAPIConfig, rest_api_resources

SESSION_NAMES = ["Race", "Sprint"]
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
TELEMETRY_SESSION = "Race"
# OpenF1 stores the starting grid under the qualifying session that set it.
GRID_SESSION_NAMES = {
    "Race": ("Qualifying",),
    "Sprint": ("Sprint Qualifying", "Sprint Shootout"),
}


def per_session(name: str, parent: str, **params) -> dict:
    return {
        "name": name,
        # Raw files are append-only, stage 2 deduplicates by session_key.
        "write_disposition": "append",
        "endpoint": {
            "path": name,
            "params": {
                "session_key": f"{{resources.{parent}.session_key}}",
                **params,
            },
        },
    }


@dlt.source(max_table_nesting=0)  # keep rows as the API sent them
def openf1_source(since: date, access_token: str | None = None):
    today = datetime.now(UTC).date()
    meeting_key = "{resources.meetings.meeting_key}"
    grid_session_names = [n for names in GRID_SESSION_NAMES.values() for n in names]

    resources = [
        {
            "name": "meetings",
            "primary_key": "meeting_key",
            "write_disposition": "append",
            "endpoint": {
                "path": "meetings",
                "params": {
                    # Later runs only request meetings after the last one fetched.
                    "date_start>": {
                        "type": "incremental",
                        "cursor_path": "date_start",
                        "initial_value": since.isoformat(),
                    },
                    "date_end<": today.isoformat(),
                    "is_cancelled": "false",
                },
            },
        },
        {
            "name": "sessions",
            "primary_key": "session_key",
            "write_disposition": "append",
            "endpoint": {
                "path": "sessions",
                "params": {
                    "meeting_key": meeting_key,
                    "session_name": SESSION_NAMES,
                },
            },
        },
        *(per_session(endpoint, "sessions") for endpoint in SESSION_ENDPOINTS),
        {
            "name": "grid_sessions",
            "selected": False,
            "endpoint": {
                "path": "sessions",
                "params": {
                    "meeting_key": meeting_key,
                    "session_name": grid_session_names,
                },
            },
        },
        per_session("starting_grid", "grid_sessions"),
        {
            "name": "race_sessions",
            "selected": False,
            "endpoint": {
                "path": "sessions",
                "params": {
                    "meeting_key": meeting_key,
                    "session_name": TELEMETRY_SESSION,
                },
            },
        },
        {
            **per_session("drivers", "race_sessions"),
            "name": "race_drivers",
            "selected": False,
        },
        per_session(
            "car_data",
            "race_drivers",
            driver_number="{resources.race_drivers.driver_number}",
        ),
    ]

    client = {"base_url": "https://api.openf1.org/v1"}
    if access_token:
        client["auth"] = {"type": "bearer", "token": access_token}

    config: RESTAPIConfig = {
        "client": client,
        "resources": resources,
    }
    yield from rest_api_resources(config)


def run(
    since: date,
    raw_dir: Path = Path("data/raw"),
    access_token: str | None = None,
) -> None:
    pipeline = dlt.pipeline(
        pipeline_name="openf1_fetch",
        destination=dlt.destinations.filesystem(bucket_url=raw_dir.resolve().as_uri()),
        dataset_name="openf1",
    )
    return pipeline.run(openf1_source(since, access_token), loader_file_format="jsonl")
