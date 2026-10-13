"""Extract step: OpenF1 API → raw zone, tracked unit by unit in meta.extract_state.

Unit = (endpoint, race_session_key, chunk_key). Every unit's outcome is written to Postgres right
away, so a rerun after a crash, Ctrl+C or --max-requests continues where the last run stopped.
"""

import logging
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import psycopg

import discovery
import endpoints
import ingest
import state
from classify import classify, record_count
from client import CLIENT_VERSION, OpenF1Client
from discovery import Filters
from raw_store import RawStore

DONE = ("done", "empty")
# Recent races are re-fetched on every run: OpenF1 may still publish or correct data.
SETTLING_DAYS = 3

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Unit:
    endpoint: str
    key: int  # race session key; the year for meetings/sessions
    chunk_key: str
    params: dict | None  # None: nothing to query (no qualifying session for the grid)
    raw_dir: str
    session_end: datetime | None  # None: no settling window (metadata)

    @property
    def id(self) -> tuple[str, int, str]:
        return self.endpoint, self.key, self.chunk_key


@dataclass
class Context:
    conn: psycopg.Connection
    store: RawStore
    client: OpenF1Client | None
    run_id: uuid.UUID
    fixed_now: datetime | None = None  # hidden --now, to test the live-window guard
    counts: Counter = field(default_factory=Counter)

    def now(self) -> datetime:
        return self.fixed_now or datetime.now(UTC)


class StopRun(Exception):
    """A planned, clean stop (live window, --max-requests); unfinished units stay pending/deferred."""


# --- planning ---------------------------------------------------------------


def units_to_run(
    candidates: list[Unit], statuses: dict[tuple[str, str], str], reset: bool
) -> list[Unit]:
    """New, pending, failed and deferred units run; done/empty ones only when reset (settling or --force)."""
    return [
        u
        for u in candidates
        if reset or statuses.get((u.endpoint, u.chunk_key)) not in DONE
    ]


def metadata_units(store: RawStore, years: range) -> list[Unit]:
    return [
        Unit(name, year, "all", {"year": year}, store.unit_dir(name, year), None)
        for year in years
        for name in endpoints.METADATA
    ]


def race_units(
    store: RawStore, race: dict, sessions: list[dict], names: tuple[str, ...]
) -> list[Unit]:
    """The session-level units of one race (drivers first, registry order)."""
    key, meeting = race["session_key"], race["meeting_key"]
    units = []
    for name in endpoints.RACE_LEVEL:
        if names and name not in names:
            continue
        queried = key
        if name == "starting_grid":
            queried = discovery.qualifying_key(sessions, meeting)
        params = {"session_key": queried} if queried is not None else None
        raw_dir = store.unit_dir(name, race["year"], meeting, key)
        units.append(Unit(name, key, "all", params, raw_dir, race["date_end"]))
    return units


def car_data_units(store: RawStore, race: dict, drivers: list[dict]) -> list[Unit]:
    key, meeting = race["session_key"], race["meeting_key"]
    return [
        Unit(
            "car_data",
            key,
            f"driver={number}",
            {"session_key": key, "driver_number": number},
            store.unit_dir("car_data", race["year"], meeting, key, number),
            race["date_end"],
        )
        for number in sorted({d["driver_number"] for d in drivers})
    ]


# --- running ----------------------------------------------------------------


def run_unit(ctx: Context, unit: Unit, sessions: list[dict]) -> str:
    """Fetch one unit, store it if usable and record its status."""
    result, manifest = None, {}
    if unit.params is None:
        status, error = "failed", "no Qualifying session found"
    else:
        result = ctx.client.get(unit.endpoint, unit.params)
        now = ctx.now()
        status, error = classify(
            result,
            now=now,
            session_end=unit.session_end,
            live=discovery.live_session(sessions, now) is not None,
            settling_days=SETTLING_DAYS,
        )
        # Only usable responses go to the raw zone: a failure never overwrites a good earlier file.
        if status in DONE:
            manifest = ctx.store.write(
                unit.raw_dir,
                result.content,
                {
                    "endpoint": unit.endpoint,
                    "url": result.url,
                    "params": unit.params,
                    "queried_session_key": unit.params.get("session_key"),
                    "race_session_key": unit.key,
                    "http_status": result.status_code,
                    "record_count": record_count(result),
                    "attempts": result.attempts,
                    "run_id": str(ctx.run_id),
                    "client_version": CLIENT_VERSION,
                },
            )

    state.record_result(
        ctx.conn,
        *unit.id,
        status=status,
        attempts=result.attempts if result else 0,
        http_status=result.status_code if result else None,
        last_error=error,
        run_id=ctx.run_id,
        record_count=manifest.get("record_count"),
        sha256=manifest.get("sha256"),
        raw_path=unit.raw_dir if manifest else None,
        fetched_at=manifest.get("fetched_at"),
    )
    ctx.counts[status] += 1
    log.info(
        "%s %s %s %s %s records=%s attempts=%s elapsed_ms=%s%s",
        ctx.run_id,
        unit.endpoint,
        unit.key,
        unit.chunk_key,
        status,
        manifest.get("record_count", 0),
        result.attempts if result else 0,
        result.elapsed_ms if result else 0,
        f" error={error}" if error else "",
    )
    return status


def execute(
    ctx: Context, units: list[Unit], sessions: list[dict], max_requests: int | None
) -> None:
    """Mark the units pending, then run them in order; stops cleanly on --max-requests or a live window."""
    for unit in units:
        state.set_pending(ctx.conn, *unit.id)
    for i, unit in enumerate(units):
        if max_requests is not None and ctx.client.requests_made >= max_requests:
            raise StopRun(f"--max-requests {max_requests} reached")
        live = discovery.live_session(sessions, ctx.now())
        if live:
            # The API is blocked until the window ends: postpone everything left in this plan.
            reason = (
                f"live window of session {live['session_key']} ({live['session_name']})"
            )
            state.defer(ctx.conn, [u.id for u in units[i:]], reason)
            ctx.counts["deferred"] += len(units) - i
            raise StopRun(f"API is live: {reason}")
        run_unit(ctx, unit, sessions)


def refresh_metadata(ctx: Context) -> list[dict]:
    """Full refresh of meetings + sessions per season (the only requests made on every run); returns all sessions."""
    sessions = discovery.load_sessions(ctx.conn)
    live = discovery.live_session(sessions, ctx.now())
    if live:
        # Planning continues on the metadata loaded earlier; the runner then defers the planned units.
        log.warning(
            "API is live (session %s), metadata refresh skipped", live["session_key"]
        )
        return sessions
    units = metadata_units(ctx.store, discovery.seasons(ctx.now()))
    execute(ctx, units, sessions, None)
    for unit in units:
        ingest.load_partition(ctx.conn, ctx.store, unit.endpoint, unit.key, ctx.run_id)
    return discovery.load_sessions(ctx.conn)


def extract(
    ctx: Context, filters: Filters, force: bool = False, max_requests: int | None = None
) -> None:
    """Refresh metadata, then plan and fetch every eligible race, oldest first."""
    sessions = refresh_metadata(ctx)
    races = discovery.eligible_races(sessions, ctx.now(), filters)
    want_car_data = not filters.endpoints or "car_data" in filters.endpoints
    log.info("%d eligible races", len(races))

    for race in races:
        key = race["session_key"]
        reset = force or ctx.now() - race["date_end"] <= timedelta(days=SETTLING_DAYS)
        statuses = state.unit_statuses(ctx.conn, key)
        units = race_units(ctx.store, race, sessions, filters.endpoints)
        execute(ctx, units_to_run(units, statuses, reset), sessions, max_requests)

        if want_car_data:
            # car_data is planned only once this race's driver list is known.
            statuses = state.unit_statuses(ctx.conn, key)
            if statuses.get(("drivers", "all")) != "done":
                log.info("%s: drivers not done, car_data not planned", key)
                continue
            drivers = ctx.store.read_records(
                ctx.store.unit_dir("drivers", race["year"], race["meeting_key"], key)
            )
            units = car_data_units(ctx.store, race, drivers)
            execute(ctx, units_to_run(units, statuses, reset), sessions, max_requests)
