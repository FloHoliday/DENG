"""Command line: a thin wrapper around the pipeline functions. Run as `uv run scripts/f1.py <command>`.

Exit codes: 0 success (deferred units allowed), 1 failed units or unexpected error,
2 configuration or database connection error, 130 interrupted (Ctrl+C).
"""

import argparse
import logging
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# The pipeline modules sit directly in src/ (no installed package).
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import psycopg

import db
import ingest
from client import OpenF1Client
from config import load_settings
from discovery import Filters
from fetch import Context, StopRun, extract
from raw_store import RawStore

log = logging.getLogger("f1")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    filters = argparse.ArgumentParser(add_help=False)
    filters.add_argument(
        "--session-key", type=int, help="only this race session, e.g. 9839"
    )
    filters.add_argument(
        "--endpoint", action="append", default=[], help="endpoint, repeatable"
    )
    filters.add_argument(
        "--force", action="store_true", help="re-fetch / reload completed units"
    )
    fetching = argparse.ArgumentParser(add_help=False)
    fetching.add_argument(
        "--max-requests", type=int, help="stop cleanly after N API requests"
    )
    # Hidden: pretend it is this time (e.g. 2026-10-11T12:00:00Z) to test the live-window guard.
    fetching.add_argument("--now", type=datetime.fromisoformat, help=argparse.SUPPRESS)

    commands.add_parser("init-db", help="create the meta and raw schemas (idempotent)")
    commands.add_parser(
        "extract",
        parents=[filters, fetching],
        help="refresh metadata, fetch planned units to the raw zone",
    )
    commands.add_parser(
        "load",
        parents=[filters],
        help="load completed partitions into raw.* (no API requests)",
    )
    commands.add_parser("run", parents=[filters, fetching], help="extract + load")
    return parser.parse_args()


def run(args: argparse.Namespace, ctx: Context) -> None:
    filters = Filters(args.session_key, tuple(args.endpoint))
    stop = None
    if args.command in ("extract", "run"):
        try:
            extract(ctx, filters, args.force, args.max_requests)
        except StopRun as exc:
            # Partitions completed before a clean stop (live window, --max-requests) are still loaded.
            stop = exc
    if args.command in ("load", "run"):
        ctx.counts += ingest.load(
            ctx.conn,
            ctx.store,
            ctx.run_id,
            args.session_key,
            filters.endpoints,
            args.force,
        )
    if stop:
        raise stop


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    # One line per unit comes from the pipeline itself; per-request lines would only repeat it.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        settings = load_settings()
        conn = db.connect(settings)
    except (KeyError, ValueError) as exc:
        log.error("Configuration error: %r (see .env.example)", exc)
        return 2
    except psycopg.OperationalError as exc:
        log.error("Cannot connect to PostgreSQL: %s", exc)
        return 2

    if args.command == "init-db":
        with conn:
            log.info("Applied %s", ", ".join(db.apply_ddl(conn)))
        return 0

    client = OpenF1Client() if args.command != "load" else None
    now = getattr(args, "now", None)
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
        run(args, ctx)
    except StopRun as stop:
        log.warning("%s", stop)
    except KeyboardInterrupt:
        # Files are written atomically and each unit's state is committed, so a rerun just continues.
        log.warning("Interrupted, unfinished units stay pending")
        exit_code = 130
    except Exception:
        log.exception("%s failed", args.command)
        exit_code = 1
    if (ctx.counts["failed"] or ctx.counts["load_failed"]) and exit_code == 0:
        exit_code = 1
    if client:
        log.info("API requests: %d", client.requests_made)
        client.close()
    log.info(
        "run %s %s: exit %d, %s",
        ctx.run_id,
        args.command,
        exit_code,
        " ".join(f"{k}={v}" for k, v in sorted(ctx.counts.items())) or "nothing to do",
    )
    conn.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
