"""Access to the meta tables: pipeline_run, extract_state, load_state (sql/001_meta.sql).

The pipeline connection runs in autocommit mode, so every state change is durable immediately
and a crash or Ctrl+C never loses the record of finished units.
"""

import uuid
from datetime import datetime

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def start_run(conn: psycopg.Connection, command: str, params: dict) -> uuid.UUID:
    run_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO meta.pipeline_run (run_id, command, params) VALUES (%s, %s, %s)",
        (run_id, command, Jsonb(params)),
    )
    return run_id


def end_run(
    conn: psycopg.Connection, run_id: uuid.UUID, outcome: str, counts: dict
) -> None:
    conn.execute(
        "UPDATE meta.pipeline_run SET ended_at = now(), outcome = %s, counts = %s WHERE run_id = %s",
        (outcome, Jsonb(counts), run_id),
    )


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


def partition_units(conn: psycopg.Connection, endpoint: str, key: int) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            SELECT chunk_key, status, raw_path, sha256, record_count FROM meta.extract_state
            WHERE endpoint = %s AND race_session_key = %s ORDER BY chunk_key
            """,
            (endpoint, key),
        ).fetchall()


def partitions(conn: psycopg.Connection) -> list[tuple[str, int]]:
    return conn.execute(
        "SELECT DISTINCT endpoint, race_session_key FROM meta.extract_state ORDER BY 2, 1"
    ).fetchall()


def load_fingerprint(conn: psycopg.Connection, endpoint: str, key: int) -> str | None:
    row = conn.execute(
        "SELECT files_fingerprint FROM meta.load_state WHERE endpoint = %s AND race_session_key = %s",
        (endpoint, key),
    ).fetchone()
    return row[0] if row else None


def save_load(
    conn: psycopg.Connection,
    endpoint: str,
    key: int,
    fingerprint: str,
    row_count: int,
    run_id: uuid.UUID,
) -> None:
    conn.execute(
        """
        INSERT INTO meta.load_state (endpoint, race_session_key, files_fingerprint, row_count, run_id)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (endpoint, race_session_key) DO UPDATE SET
          files_fingerprint = EXCLUDED.files_fingerprint, row_count = EXCLUDED.row_count,
          run_id = EXCLUDED.run_id, loaded_at = now()
        """,
        (endpoint, key, fingerprint, row_count, run_id),
    )


def status_counts(conn: psycopg.Connection, keys: list[int] | None) -> list[tuple]:
    """(endpoint, status, units) for the given race keys (None = all)."""
    return conn.execute(
        """
        SELECT endpoint, status, count(*) FROM meta.extract_state
        WHERE %(keys)s::int[] IS NULL OR race_session_key = ANY(%(keys)s)
        GROUP BY 1, 2 ORDER BY 1, 2
        """,
        {"keys": keys},
    ).fetchall()


def problems(conn: psycopg.Connection, keys: list[int] | None) -> list[tuple]:
    """Failed and deferred units with their last error."""
    return conn.execute(
        """
        SELECT endpoint, race_session_key, chunk_key, status, http_status, last_error
        FROM meta.extract_state
        WHERE status IN ('failed', 'deferred')
          AND (%(keys)s::int[] IS NULL OR race_session_key = ANY(%(keys)s))
        ORDER BY race_session_key, endpoint, chunk_key
        """,
        {"keys": keys},
    ).fetchall()
