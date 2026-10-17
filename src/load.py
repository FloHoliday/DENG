"""Load step: load the raw JSON of every completed session in data/raw into typed PostgreSQL tables."""

import json
import os
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import URL, create_engine, text
from upath import UPath

from fetch import SESSION_ENDPOINTS

SCHEMA = Path(__file__).parents[1] / "sql/schema.sql"
TABLES = [*SESSION_ENDPOINTS, "starting_grid", "car_data"]
# starting_grid.session_key is the qualifying session, so it is replaced by its race_session_key.
KEY_COLUMNS = {"starting_grid": "race_session_key"}
COLUMN_NAME = re.compile(r"[a-z][a-z0-9_]*")


def create_engine_from_env():
    url = URL.create(
        "postgresql+psycopg",
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=os.environ["POSTGRES_DB"],
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )
    return create_engine(
        url, connect_args={"connect_timeout": 10}, hide_parameters=True
    )


def read_json(path: UPath):
    return json.loads(path.read_text(encoding="utf-8"))


def table_files(session_dir: UPath, table: str) -> list[UPath]:
    if table == "car_data":
        return sorted(session_dir.glob("car_data/*.json"))
    return [session_dir / f"{table}.json"]


def insert(connection, table: str, rows: list[dict], conflict_key: str | None = None):
    """Insert each field into its typed column; an unknown field or wrong type fails the transaction."""
    columns = list(dict.fromkeys(c for row in rows for c in row))
    for column in columns:
        # Field names come from the API and end up in SQL.
        if not COLUMN_NAME.fullmatch(column):
            raise ValueError(f"{table}: invalid field name {column!r}")
    names = ", ".join(f'"{c}"' for c in columns)
    values = ", ".join(f":{c}" for c in columns)
    sql = f"INSERT INTO public.{table} ({names}) VALUES ({values})"
    if conflict_key:
        updates = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in columns)
        sql += (
            f" ON CONFLICT ({conflict_key}) DO UPDATE SET {updates}, loaded_at = now()"
        )
    connection.execute(text(sql), [{c: row.get(c) for c in columns} for row in rows])


def load_session(session_dir: UPath, engine) -> int:
    """Replace one session's rows in one transaction; returns the number of rows loaded."""
    success = read_json(session_dir / "_SUCCESS")
    session_key = int(session_dir.name.split("_")[0])
    meeting = read_json(session_dir.parent / "meeting.json")
    sessions = read_json(session_dir.parent / "sessions.json")

    # A failed session restores its earlier rows.
    with engine.begin() as connection:
        # In this transaction, wait at most 10 seconds to acquire a database lock.
        connection.execute(text("SET LOCAL lock_timeout = '10s'"))
        # Prevent two simultaneous jobs from replacing the same session together.
        connection.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": session_key})
        insert(connection, "meetings", [meeting], "meeting_key")
        insert(connection, "sessions", sessions, "session_key")

        loaded = 0
        for table in TABLES:
            key = KEY_COLUMNS.get(table, "session_key")
            connection.execute(
                text(f"DELETE FROM public.{table} WHERE {key} = :k"),
                {"k": session_key},
            )
            for path in table_files(session_dir, table):
                rows = read_json(path)
                if rows:
                    insert(
                        connection, table, [{**row, key: session_key} for row in rows]
                    )

            expected = sum(
                n
                for name, n in success["row_counts"].items()
                if name.split("/")[0] == table
            )
            actual = connection.scalar(
                text(f"SELECT COUNT(*) FROM public.{table} WHERE {key} = :k"),
                {"k": session_key},
            )
            if actual != expected:
                raise ValueError(
                    f"{session_dir}: {table} has {actual} rows, _SUCCESS says {expected}; rolling back this session."
                )
            loaded += actual

        connection.execute(
            text("""
                INSERT INTO public.loaded_sessions (session_key, completed_at) VALUES (:k, :c)
                ON CONFLICT (session_key) DO UPDATE
                SET completed_at = EXCLUDED.completed_at, loaded_at = now()
            """),
            {"k": session_key, "c": success["completed_at"]},
        )
    return loaded


def run(raw_dir: UPath) -> int:
    """Load every session whose _SUCCESS marker is newer than its last load; returns the number loaded."""
    engine = create_engine_from_env()
    try:
        with engine.begin() as connection:
            connection.execute(text(SCHEMA.read_text(encoding="utf-8")))
            loaded_markers = dict(
                connection.execute(
                    text("SELECT session_key, completed_at FROM public.loaded_sessions")
                ).fetchall()
            )

        count = 0
        for marker in sorted(raw_dir.glob("**/_SUCCESS")):
            session_dir = marker.parent
            session_key = int(session_dir.name.split("_")[0])
            completed_at = datetime.fromisoformat(read_json(marker)["completed_at"])
            if loaded_markers.get(session_key) == completed_at:
                print(f"skip  {session_dir} (already loaded)")
                continue
            rows = load_session(session_dir, engine)
            print(f"load  {session_dir}: {rows:,} rows")
            count += 1
        print(f"Loaded {count} sessions into PostgreSQL")
        return count
    finally:
        engine.dispose()
