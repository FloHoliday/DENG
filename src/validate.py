"""Validate step: compare data/raw with the database and run the SQL checks in sql/verify.sql."""

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from upath import UPath

from load import create_engine_from_env

VERIFY_SQL = Path(__file__).parents[1] / "sql/verify.sql"


def unloaded_sessions(raw_dir: UPath, connection) -> list[str]:
    """Session folders whose _SUCCESS marker is not the one recorded in loaded_sessions."""
    loaded = dict(
        connection.execute(
            text("SELECT session_key, completed_at FROM raw.loaded_sessions")
        ).fetchall()
    )
    missing = []
    for marker in sorted(raw_dir.glob("**/_SUCCESS")):
        session_key = int(marker.parent.name.split("_")[0])
        completed_at = json.loads(marker.read_text(encoding="utf-8"))["completed_at"]
        if loaded.get(session_key) != datetime.fromisoformat(completed_at):
            missing.append(marker.parent.name)
    return missing


def run(raw_dir: UPath) -> int:
    """Print PASS/FAIL per check; returns the number of failed checks."""
    engine = create_engine_from_env()
    try:
        with engine.connect() as connection:
            missing = unloaded_sessions(raw_dir, connection)
            results = [
                (
                    "every fetched session (_SUCCESS) is loaded",
                    len(missing),
                    ", ".join(missing[:5]),
                )
            ]
            results += connection.execute(
                text(VERIFY_SQL.read_text(encoding="utf-8"))
            ).fetchall()
    finally:
        engine.dispose()

    for check, failures, detail in results:
        status = "PASS" if failures == 0 else "FAIL"
        print(f"{status}  {check}" + (f"  ({failures}: {detail})" if failures else ""))
    failed = sum(1 for _, failures, _ in results if failures)
    print(f"{len(results) - failed} of {len(results)} checks passed")
    return failed
