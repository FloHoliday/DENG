"""Command line: a thin wrapper around the pipeline functions. Run as `uv run src/cli.py <command>`.

Exit codes: 0 success (deferred units allowed), 1 failed units or unexpected error,
2 configuration or database connection error, 130 interrupted (Ctrl+C).
"""

import logging
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

import psycopg
import typer

import db
import ingest
from client import OpenF1Client
from config import Settings, load_settings
from discovery import Filters
from fetch import Context, StopRun, extract
from raw_store import RawStore

app = typer.Typer(add_completion=False, no_args_is_help=True)
log = logging.getLogger("f1")

SessionKey = Annotated[
    int | None, typer.Option(help="Only this race session, e.g. 9839.")
]
Endpoint = Annotated[
    list[str] | None, typer.Option("--endpoint", help="Endpoint, repeatable.")
]
Force = Annotated[bool, typer.Option(help="Re-fetch / reload completed units.")]
MaxRequests = Annotated[
    int | None, typer.Option(help="Stop cleanly after N API requests.")
]
Now = Annotated[
    datetime | None,
    typer.Option(
        hidden=True,
        formats=["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"],
        help="Pretend it is this time, e.g. 2026-10-11T12:00:00Z (tests the live guard).",
    ),
]


@app.callback()
def main() -> None:
    """OpenF1 Race data: extract to the raw zone, load into PostgreSQL."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    # One line per unit comes from the pipeline itself; per-request lines would only repeat it.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _settings() -> Settings:
    try:
        return load_settings()
    except (KeyError, ValueError) as exc:
        print(f"Configuration error: {exc!r} (see .env.example)", file=sys.stderr)
        raise typer.Exit(2) from exc


def _connect(settings: Settings) -> psycopg.Connection:
    try:
        return db.connect(settings)
    except psycopg.OperationalError as exc:
        log.error("Cannot connect to PostgreSQL: %s", exc)
        raise typer.Exit(2) from exc


def _run(
    command: str,
    body: Callable[[Context], None],
    *,
    with_client: bool = False,
    now: datetime | None = None,
) -> None:
    """Run one command and turn its result into an exit code."""
    settings = _settings()
    conn = _connect(settings)
    client = OpenF1Client() if with_client else None
    ctx = Context(
        conn=conn,
        store=RawStore(settings.raw_uri),
        client=client,
        run_id=uuid.uuid4(),
        # A --now without offset is taken as UTC.
        fixed_now=(now if now.tzinfo else now.replace(tzinfo=UTC)) if now else None,
    )
    exit_code = 0
    try:
        body(ctx)
    except StopRun as stop:
        log.warning("%s", stop)
    except KeyboardInterrupt:
        # Files are written atomically and each unit's state is committed, so a rerun just continues.
        log.warning("Interrupted, unfinished units stay pending")
        exit_code = 130
    except Exception:
        log.exception("%s failed", command)
        exit_code = 1
    if (ctx.counts["failed"] or ctx.counts["load_failed"]) and exit_code == 0:
        exit_code = 1
    if client:
        log.info("API requests: %d", client.requests_made)
        client.close()
    log.info(
        "run %s %s: exit %d, %s",
        ctx.run_id,
        command,
        exit_code,
        " ".join(f"{k}={v}" for k, v in sorted(ctx.counts.items())) or "nothing to do",
    )
    conn.close()
    raise typer.Exit(exit_code)


@app.command("init-db")
def init_db() -> None:
    """Create the meta and raw schemas (idempotent)."""
    with _connect(_settings()) as conn:
        log.info("Applied %s", ", ".join(db.apply_ddl(conn)))


@app.command("extract")
def extract_cmd(
    session_key: SessionKey = None,
    endpoint: Endpoint = None,
    force: Force = False,
    max_requests: MaxRequests = None,
    now: Now = None,
) -> None:
    """Refresh metadata, then fetch all planned units of the selected races to the raw zone."""
    filters = Filters(session_key, tuple(endpoint or ()))
    _run(
        "extract",
        lambda ctx: extract(ctx, filters, force, max_requests),
        with_client=True,
        now=now,
    )


@app.command("load")
def load_cmd(
    session_key: SessionKey = None, endpoint: Endpoint = None, force: Force = False
) -> None:
    """Load completed partitions from the raw zone into raw.* (no API requests)."""

    def body(ctx: Context) -> None:
        ctx.counts += ingest.load(
            ctx.conn, ctx.store, ctx.run_id, session_key, tuple(endpoint or ()), force
        )

    _run("load", body)


@app.command("run")
def run_cmd(
    session_key: SessionKey = None,
    endpoint: Endpoint = None,
    force: Force = False,
    max_requests: MaxRequests = None,
    now: Now = None,
) -> None:
    """Metadata refresh + extract + load."""
    filters = Filters(session_key, tuple(endpoint or ()))

    def body(ctx: Context) -> None:
        stop = None
        try:
            extract(ctx, filters, force, max_requests)
        except StopRun as exc:
            # Partitions completed before a clean stop (live window, --max-requests) are still loaded.
            stop = exc
        ctx.counts += ingest.load(
            ctx.conn, ctx.store, ctx.run_id, session_key, filters.endpoints, force
        )
        if stop:
            raise stop

    _run("run", body, with_client=True, now=now)


if __name__ == "__main__":
    app()
