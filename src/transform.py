"""Transform step: rebuild the staging views, core and mart models from sql/transform/*.sql in one transaction."""

import time
from pathlib import Path

from sqlalchemy import text

from load import create_engine_from_env

SQL_DIR = Path(__file__).parents[1] / "sql/transform"


def run(full_refresh: bool = False) -> None:
    """Run every SQL file in name order; readers see the old models until the commit."""
    engine = create_engine_from_env()
    try:
        with engine.begin() as connection:
            # Only one transform at a time (a scheduled run and a manual rerun).
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('transform'))")
            )
            # Views and materialized views are always rebuilt, so a changed definition
            # is picked up and a rerun gives the same result. The incremental telemetry
            # table in core is kept, unless a full refresh is requested.
            connection.execute(text("DROP SCHEMA IF EXISTS marts CASCADE"))
            connection.execute(text("DROP SCHEMA IF EXISTS staging CASCADE"))
            if full_refresh:
                connection.execute(text("DROP SCHEMA IF EXISTS core CASCADE"))
            for path in sorted(SQL_DIR.glob("*.sql")):
                start = time.monotonic()
                connection.execute(text(path.read_text(encoding="utf-8")))
                print(f"ran   {path.name:<40} in {time.monotonic() - start:.1f}s")
        print("Transform complete")
    finally:
        engine.dispose()
