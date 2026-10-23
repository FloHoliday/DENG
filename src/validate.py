"""Validate step: compare data/raw with the database and run the SQL checks in sql/verify.sql."""

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from upath import UPath

from load import create_engine_from_env, success_markers

VERIFY_SQL = Path(__file__).parents[1] / "sql/verify.sql"


def unloaded_sessions(
    raw_dir: UPath, connection, meeting_key: int | None = None
) -> list[str]:
    """Session folders whose _SUCCESS marker is not the one recorded in loaded_sessions."""
    loaded = dict(
        connection.execute(
            text("SELECT session_key, completed_at FROM raw.loaded_sessions")
        ).fetchall()
    )
    missing = []
    for marker in success_markers(raw_dir, meeting_key):
        session_key = int(marker.parent.name.split("_")[0])
        completed_at = json.loads(marker.read_text(encoding="utf-8"))["completed_at"]
        if loaded.get(session_key) != datetime.fromisoformat(completed_at):
            missing.append(marker.parent.name)
    return missing


def race_loaded(connection, meeting_key: int) -> bool:
    """Whether the race session of the meeting is in loaded_sessions."""
    return bool(
        connection.scalar(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM raw.loaded_sessions AS ls
                    JOIN raw.sessions AS s USING (session_key)
                    WHERE s.meeting_key = :k AND s.session_name = 'Race'
                )
            """),
            {"k": meeting_key},
        )
    )


def run(raw_dir: UPath, meeting_key: int | None = None) -> int:
    """Print PASS/FAIL per check; returns the number of failed checks.

    With `meeting_key`, only that meeting's sessions are compared with data/raw, and its race
    must be loaded (so a fetch that wrote nothing fails); the SQL checks always cover everything.
    """
    engine = create_engine_from_env()
    try:
        with engine.connect() as connection:
            missing = unloaded_sessions(raw_dir, connection, meeting_key)
            results = [
                (
                    "every fetched session (_SUCCESS) is loaded",
                    len(missing),
                    ", ".join(missing[:5]),
                )
            ]
            if meeting_key:
                results.append(
                    (
                        f"the race of meeting {meeting_key} is loaded",
                        0 if race_loaded(connection, meeting_key) else 1,
                        "no loaded Race session",
                    )
                )
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
