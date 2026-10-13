"""Access to meta.extract_state: one row per extract unit (sql/001_meta.sql).

The pipeline connection runs in autocommit mode, so every state change is durable immediately
and a crash or Ctrl+C never loses the record of finished units.
"""

import uuid
from datetime import datetime

import psycopg


def unit_statuses(conn: psycopg.Connection, key: int) -> dict[tuple[str, str], str]:
    """{(endpoint, chunk_key): status} of every unit stored for one race (or metadata year)."""
    rows = conn.execute(
        "SELECT endpoint, chunk_key, status FROM meta.extract_state WHERE race_session_key = %s",
        (key,),
    ).fetchall()
    return {(endpoint, chunk): status for endpoint, chunk, status in rows}


def set_pending(conn: psycopg.Connection, endpoint: str, key: int, chunk: str) -> None:
    conn.execute(
        """
        INSERT INTO meta.extract_state (endpoint, race_session_key, chunk_key, status)
        VALUES (%s, %s, %s, 'pending')
        ON CONFLICT (endpoint, race_session_key, chunk_key)
        DO UPDATE SET status = 'pending', updated_at = now()
        """,
        (endpoint, key, chunk),
    )


def record_result(
    conn: psycopg.Connection,
    endpoint: str,
    key: int,
    chunk: str,
    *,
    status: str,
    attempts: int,
    http_status: int | None,
    last_error: str | None,
    run_id: uuid.UUID,
    record_count: int | None = None,
    sha256: str | None = None,
    raw_path: str | None = None,
    fetched_at: datetime | None = None,
) -> None:
    """Store the outcome of one unit; a failed re-fetch keeps the path/hash of the last stored file."""
    conn.execute(
        """
        UPDATE meta.extract_state SET
          status = %(status)s,
          attempts = attempts + %(attempts)s,
          http_status = %(http_status)s,
          last_error = %(last_error)s,
          record_count = coalesce(%(record_count)s, record_count),
          sha256 = coalesce(%(sha256)s, sha256),
          raw_path = coalesce(%(raw_path)s, raw_path),
          fetched_at = coalesce(%(fetched_at)s, fetched_at),
          last_run_id = %(run_id)s,
          updated_at = now()
        WHERE endpoint = %(endpoint)s AND race_session_key = %(key)s AND chunk_key = %(chunk)s
        """,
        {
            "endpoint": endpoint,
            "key": key,
            "chunk": chunk,
            "status": status,
            "attempts": attempts,
            "http_status": http_status,
            "last_error": last_error,
            "record_count": record_count,
            "sha256": sha256,
            "raw_path": raw_path,
            "fetched_at": fetched_at,
            "run_id": run_id,
        },
    )


def defer(
    conn: psycopg.Connection, units: list[tuple[str, int, str]], reason: str
) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            UPDATE meta.extract_state
            SET status = 'deferred', http_status = NULL, last_error = %s, updated_at = now()
            WHERE endpoint = %s AND race_session_key = %s AND chunk_key = %s
            """,
            [(reason, *unit) for unit in units],
        )
