"""Command line: a thin wrapper around the pipeline functions. Run as `uv run src/cli.py <command>`.

Exit codes: 0 success (deferred units allowed), 1 failed units or unexpected error,
2 configuration or database connection error, 130 interrupted (Ctrl+C).
"""

import logging
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

import psycopg
import typer

import db
import discovery
import state
from client import OpenF1Client
from config import Settings, load_settings
from discovery import Filters
from fetch import Context, StopRun, extract
from logging_setup import setup_logging
from raw_store import RawStore

app = typer.Typer(add_completion=False, no_args_is_help=True)
log = logging.getLogger("f1")

Year = Annotated[list[int] | None, typer.Option("--year", help="Season, repeatable.")]
MeetingKey = Annotated[int | None, typer.Option(help="Only this race weekend.")]
SessionKey = Annotated[int | None, typer.Option(help="Only this race session.")]
Endpoint = Annotated[
    list[str] | None, typer.Option("--endpoint", help="Endpoint, repeatable.")
]
Profile = Annotated[
    str | None, typer.Option(help="'review': only REVIEW_SESSION_KEY (fast).")
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


def _settings() -> Settings:
    """Load settings and configure logging; config errors exit with code 2."""
    try:
        settings = load_settings()
    except (KeyError, ValueError) as exc:
        print(f"Configuration error: {exc!r} (see .env.example)", file=sys.stderr)
        raise typer.Exit(2) from exc
    setup_logging(settings.log_level)
    return settings


def _connect(settings: Settings) -> psycopg.Connection:
    try:
        return db.connect(settings)
    except psycopg.OperationalError as exc:
        log.error("Cannot connect to PostgreSQL: %s", exc)
        raise typer.Exit(2) from exc


def _filters(settings, year, meeting_key, session_key, endpoint, profile) -> Filters:
    if profile == "review":
        session_key = settings.review_session_key
    elif profile is not None:
        raise typer.BadParameter(f"unknown profile {profile!r}", param_hint="--profile")
    return Filters(tuple(year or ()), meeting_key, session_key, tuple(endpoint or ()))


def _run(
    command: str,
    params: dict,
    body: Callable[[Context], None],
    *,
    with_client: bool = False,
    now: datetime | None = None,
) -> None:
    """Run one command as a recorded pipeline run and turn its result into an exit code."""
    settings = _settings()
    conn = _connect(settings)
    client = OpenF1Client(settings) if with_client else None
    params = {
        k: v.isoformat() if isinstance(v, datetime) else v for k, v in params.items()
    }
    ctx = Context(
        settings=settings,
        conn=conn,
        store=RawStore(settings.raw_uri),
        client=client,
        run_id=state.start_run(conn, command, params),
        # A --now without offset is taken as UTC.
        fixed_now=(now if now.tzinfo else now.replace(tzinfo=UTC)) if now else None,
    )
    exit_code = 0
    try:
        body(ctx)
        outcome = "partial" if ctx.counts["deferred"] else "success"
    except StopRun as stop:
        log.warning("%s", stop)
        outcome = stop.outcome
    except KeyboardInterrupt:
        # Files are written atomically and each unit's state is committed, so a rerun just continues.
        log.warning("Interrupted, unfinished units stay pending")
        outcome, exit_code = "stopped", 130
    except Exception:
        log.exception("%s failed", command)
        outcome, exit_code = "failed", 1
    if ctx.counts["failed"] and exit_code == 0:
        outcome, exit_code = "failed", 1
    state.end_run(conn, ctx.run_id, outcome, dict(ctx.counts))
    if client:
        log.info("API requests: %d", client.requests_made)
    log.info(
        "run %s %s: %s %s",
        ctx.run_id,
        command,
        outcome,
        " ".join(f"{k}={v}" for k, v in sorted(ctx.counts.items()))
        or "(nothing to do)",
    )
    conn.close()
    if client:
        client.close()
    raise typer.Exit(exit_code)


@app.command("init-db")
def init_db() -> None:
    """Create the meta and raw schemas (idempotent)."""
    settings = _settings()
    with _connect(settings) as conn:
        applied = db.apply_ddl(conn)
        run_id = state.start_run(conn, "init-db", {"applied": applied})
        state.end_run(conn, run_id, "success", {})
    log.info("Applied %s", ", ".join(applied))


@app.command("extract")
def extract_cmd(
    year: Year = None,
    meeting_key: MeetingKey = None,
    session_key: SessionKey = None,
    endpoint: Endpoint = None,
    profile: Profile = None,
    force: Force = False,
    max_requests: MaxRequests = None,
    dry_run: Annotated[
        bool, typer.Option(help="Only print the plan (metadata is still refreshed).")
    ] = False,
    now: Now = None,
) -> None:
    """Refresh metadata, then fetch all planned units of the selected races to the raw zone."""

    def body(ctx: Context) -> None:
        filters = _filters(
            ctx.settings, year, meeting_key, session_key, endpoint, profile
        )
        lines = extract(ctx, filters, force, max_requests, dry_run)
        if dry_run:
            print("\n".join(lines) or "Nothing to extract.")

    _run("extract", locals_params(locals()), body, with_client=True, now=now)


@app.command("status")
def status_cmd(
    year: Year = None,
    meeting_key: MeetingKey = None,
    session_key: SessionKey = None,
    endpoint: Endpoint = None,
    profile: Profile = None,
) -> None:
    """Units per endpoint and status; lists failed and deferred units with their last error."""

    def body(ctx: Context) -> None:
        filters = _filters(
            ctx.settings, year, meeting_key, session_key, endpoint, profile
        )
        keys = _race_keys(ctx, filters)
        rows = [
            r for r in state.status_counts(ctx.conn, keys) if _wanted(r[0], filters)
        ]
        statuses = ["pending", "done", "empty", "deferred", "failed"]
        table: dict[str, dict[str, int]] = {}
        for ep, status, n in rows:
            table.setdefault(ep, {})[status] = n
        print(f"{'endpoint':<16}" + "".join(f"{s:>10}" for s in statuses))
        for ep, counts in table.items():
            print(f"{ep:<16}" + "".join(f"{counts.get(s, 0):>10}" for s in statuses))
        problems = [p for p in state.problems(ctx.conn, keys) if _wanted(p[0], filters)]
        if problems:
            print("\nfailed / deferred:")
            for ep, key, chunk, status, http, error in problems:
                print(f"  {status:<8} {ep} {key} {chunk} http={http} {error}")

    _run("status", locals_params(locals()), body)


def _race_keys(ctx: Context, filters: Filters) -> list[int] | None:
    """Race session keys (plus metadata years) matching the filters; None = no race filter."""
    if not (filters.years or filters.meeting_key or filters.session_key):
        return None
    races = discovery.eligible_races(
        discovery.load_sessions(ctx.conn),
        ctx.now(),
        ctx.settings.scope_years,
        filters,
    )
    return [r["session_key"] for r in races] + list(filters.years)


def _wanted(endpoint: str, filters: Filters) -> bool:
    return not filters.endpoints or endpoint in filters.endpoints


def locals_params(values: dict) -> dict:
    """The command's CLI arguments, recorded in meta.pipeline_run.params."""
    return {k: v for k, v in values.items() if k != "body"}


if __name__ == "__main__":
    app()
