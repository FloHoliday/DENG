"""Load step: raw zone → raw.<endpoint> tables, one partition (endpoint, race_session_key) at a time.

Each load replaces the whole partition (DELETE + COPY) in one transaction: OpenF1 rows have no
reliable natural key, so replacing the partition is the simplest provably idempotent operation.
"""

import hashlib
import logging
import time
import uuid
from collections import Counter

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from raw_store import RawStore, parse_records

LINEAGE = ["_race_session_key", "_raw_path", "_sha256", "_run_id", "_extra"]

log = logging.getLogger(__name__)
_warned: set[tuple[str, str]] = set()


class ReconciliationError(Exception):
    pass


def table_columns(conn: psycopg.Connection, endpoint: str) -> list[str]:
    """The API field columns of raw.<endpoint>; sql/002_raw.sql is the single source of truth."""
    rows = conn.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'raw' AND table_name = %s AND column_name NOT LIKE '\\_%%'
        ORDER BY ordinal_position
        """,
        (endpoint,),
    ).fetchall()
    return [name for (name,) in rows]


def _extra(endpoint: str, record: dict, columns: list[str]) -> Jsonb | None:
    """Fields without a column (new or unexpected API fields); warns once per endpoint and field."""
    extra = {k: v for k, v in record.items() if k not in columns}
    for field in extra:
        if (endpoint, field) not in _warned:
            _warned.add((endpoint, field))
            log.warning("%s: unknown field %r stored in _extra", endpoint, field)
    return Jsonb(extra) if extra else None


def load_partition(
    conn: psycopg.Connection,
    store: RawStore,
    endpoint: str,
    key: int,
    run_id: uuid.UUID,
    force: bool = False,
) -> int | None:
    """Load one partition; returns the row count, or None if it was skipped (not ready or unchanged)."""
    with conn.cursor(row_factory=dict_row) as cur:
        units = cur.execute(
            """
            SELECT status, raw_path, sha256 FROM meta.extract_state
            WHERE endpoint = %s AND race_session_key = %s ORDER BY chunk_key
            """,
            (endpoint, key),
        ).fetchall()
    if not units or any(u["status"] not in ("done", "empty") for u in units):
        log.info("skip load %s %s: not all units done/empty", endpoint, key)
        return None
    # Changes whenever any chunk file of the partition changes.
    fingerprint = hashlib.sha256(
        "\n".join(sorted(u["sha256"] for u in units)).encode()
    ).hexdigest()
    loaded = conn.execute(
        "SELECT files_fingerprint FROM meta.load_state WHERE endpoint = %s AND race_session_key = %s",
        (endpoint, key),
    ).fetchone()
    if not force and loaded and loaded[0] == fingerprint:
        log.info("skip load %s %s: unchanged", endpoint, key)
        return None

    start = time.monotonic()
    columns = table_columns(conn, endpoint)
    table = sql.Identifier("raw", endpoint)
    copy_sql = sql.SQL("COPY {} ({}) FROM STDIN").format(
        table, sql.SQL(", ").join(map(sql.Identifier, columns + LINEAGE))
    )
    expected = 0
    # A failure anywhere rolls back the whole partition, so the previous rows stay.
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '10s'")
        cur.execute(
            sql.SQL("DELETE FROM {} WHERE _race_session_key = %s").format(table), (key,)
        )
        with cur.copy(copy_sql) as copy:
            for unit in units:
                payload = store.read_payload(unit["raw_path"])
                if hashlib.sha256(payload).hexdigest() != unit["sha256"]:
                    raise ReconciliationError(
                        f"{unit['raw_path']}: file does not match the sha256 recorded at extract"
                    )
                expected += store.read_manifest(unit["raw_path"])["record_count"]
                lineage = [key, unit["raw_path"], unit["sha256"], run_id]
                for record in parse_records(payload):
                    values = [record.get(c) for c in columns]
                    copy.write_row(
                        values + lineage + [_extra(endpoint, record, columns)]
                    )
        inserted = cur.execute(
            sql.SQL("SELECT count(*) FROM {} WHERE _race_session_key = %s").format(
                table
            ),
            (key,),
        ).fetchone()[0]
        if inserted != expected:
            raise ReconciliationError(
                f"{endpoint} {key}: inserted {inserted} rows, manifests say {expected}"
            )
        cur.execute(
            """
            INSERT INTO meta.load_state (endpoint, race_session_key, files_fingerprint, row_count, run_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (endpoint, race_session_key) DO UPDATE SET
              files_fingerprint = EXCLUDED.files_fingerprint, row_count = EXCLUDED.row_count,
              run_id = EXCLUDED.run_id, loaded_at = now()
            """,
            (endpoint, key, fingerprint, inserted, run_id),
        )
    log.info(
        "loaded %s %s: %d rows in %d ms",
        endpoint,
        key,
        inserted,
        (time.monotonic() - start) * 1000,
    )
    return inserted


def load(
    conn: psycopg.Connection,
    store: RawStore,
    run_id: uuid.UUID,
    session_key: int | None = None,
    names: tuple[str, ...] = (),
    force: bool = False,
) -> Counter:
    """Load every extracted partition (optionally one race / some endpoints); one failure doesn't stop the rest."""
    counts = Counter()
    partitions = conn.execute(
        "SELECT DISTINCT endpoint, race_session_key FROM meta.extract_state ORDER BY 2, 1"
    ).fetchall()
    for endpoint, key in partitions:
        if session_key not in (None, key) or (names and endpoint not in names):
            continue
        try:
            rows = load_partition(conn, store, endpoint, key, run_id, force)
        except (ReconciliationError, psycopg.Error, OSError, ValueError) as exc:
            log.error("load %s %s failed, previous rows kept: %s", endpoint, key, exc)
            counts["load_failed"] += 1
            continue
        counts["loaded" if rows is not None else "load_skipped"] += 1
    return counts
