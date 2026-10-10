"""Command line: a thin wrapper around the pipeline functions. Run as `uv run src/cli.py <command>`."""

import logging
import sys

import psycopg
import typer

import db
from config import load_settings
from logging_setup import setup_logging

app = typer.Typer(add_completion=False, no_args_is_help=True)
log = logging.getLogger("f1")


@app.callback()
def main() -> None:
    """OpenF1 Race data: extract to the raw zone, load into PostgreSQL."""


def _settings():
    """Load settings and configure logging; config errors exit with code 2."""
    try:
        settings = load_settings()
    except (KeyError, ValueError) as exc:
        print(f"Configuration error: {exc!r} (see .env.example)", file=sys.stderr)
        raise typer.Exit(2) from exc
    setup_logging(settings.log_level)
    return settings


def _connect(settings):
    try:
        return db.connect(settings)
    except psycopg.OperationalError as exc:
        log.error("Cannot connect to PostgreSQL: %s", exc)
        raise typer.Exit(2) from exc


@app.command("init-db")
def init_db() -> None:
    """Create the meta and raw schemas (idempotent)."""
    settings = _settings()
    with _connect(settings) as conn:
        applied = db.apply_ddl(conn)
    log.info("Applied %s", ", ".join(applied))


if __name__ == "__main__":
    app()
