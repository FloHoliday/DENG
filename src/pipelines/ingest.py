"""Load the raw JSONL files of stage 1 into PostgreSQL staging tables."""

import os
import sys
from pathlib import Path

import dlt
from dlt.sources.filesystem import filesystem, read_jsonl

from pipelines.fetch import DATASET, SESSION_ENDPOINTS

KEYS = {"meetings": "meeting_key", "sessions": "session_key"}
# Re-loading a session replaces all its rows.
PER_SESSION = {"disposition": "merge", "strategy": "delete-insert"}


def without_dlt_columns(row: dict) -> dict:
    # Stage 1 bookkeeping, this pipeline adds its own.
    return {k: v for k, v in row.items() if not k.startswith("_dlt_")}


@dlt.source
def openf1_staged(raw_dir: Path):
    tables = ["meetings", "sessions", *SESSION_ENDPOINTS, "starting_grid", "car_data"]
    for table in tables:
        files = filesystem(
            bucket_url=(raw_dir / DATASET).resolve().as_uri(),
            file_glob=f"{table}/*.jsonl",
            # Only files written since the last load.
            incremental=dlt.sources.incremental("modification_date"),
        ).with_name(f"{table}_files")
        resource = (files | read_jsonl()).add_map(without_dlt_columns)
        if table in KEYS:
            resource.apply_hints(primary_key=KEYS[table], write_disposition="merge")
        else:
            resource.apply_hints(merge_key="session_key", write_disposition=PER_SESSION)
        yield resource.with_name(table)


def postgres_credentials() -> str:
    missing = [
        v
        for v in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
        if not os.environ.get(v)
    ]
    if missing:
        sys.exit(f"Set {', '.join(missing)} (see .env.example)")
    env = os.environ
    return (
        f"postgresql://{env['POSTGRES_USER']}:{env['POSTGRES_PASSWORD']}"
        f"@{env.get('POSTGRES_HOST', 'localhost')}:{env.get('POSTGRES_PORT', '5432')}"
        f"/{env['POSTGRES_DB']}"
    )


def run(raw_dir: Path = Path("data/raw")) -> None:
    pipeline = dlt.pipeline(
        pipeline_name="openf1_ingest",
        destination=dlt.destinations.postgres(credentials=postgres_credentials()),
        dataset_name="openf1_raw",
    )
    return pipeline.run(openf1_staged(raw_dir))
