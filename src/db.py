"""PostgreSQL connection and DDL."""

from pathlib import Path

import psycopg

from config import Settings

SQL_DIR = Path(__file__).parents[1] / "sql"


def connect(settings: Settings) -> psycopg.Connection:
    """Autocommit: each state update is durable at once; multi-statement work uses conn.transaction()."""
    return psycopg.connect(
        autocommit=True,
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        connect_timeout=10,
    )


def apply_ddl(conn: psycopg.Connection) -> list[str]:
    """Run every sql/*.sql file in name order in one transaction; the files are idempotent (IF NOT EXISTS)."""
    files = sorted(SQL_DIR.glob("*.sql"))
    with conn.transaction():
        for path in files:
            conn.execute(path.read_text(encoding="utf-8"))
    return [path.name for path in files]
