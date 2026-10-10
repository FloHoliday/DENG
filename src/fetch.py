"""Extract step: OpenF1 API → raw zone, tracked unit by unit in meta.extract_state.

Unit = (endpoint, race_session_key, chunk_key). Every unit's outcome is written to Postgres right
away, so a rerun after a crash, Ctrl+C or --max-requests continues where the last run stopped.
"""

import logging
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
from config import Settings
from discovery import Filters
from raw_store import RawStore

DONE = ("done", "empty")
CAR_DATA_ESTIMATE = (
    20  # drivers per race, for --dry-run before the driver list is known
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Unit:
    endpoint: str
    key: int  # race session key; the year for meetings/sessions
    chunk_key: str
    params: dict | None  # None: nothing to query (no qualifying session for the grid)
    raw_dir: str
    session_end: datetime | None  # None: no settling window (metadata)
    queried_session_key: int | None = None

    @property
    def id(self) -> tuple[str, int, str]:
        return self.endpoint, self.key, self.chunk_key


@dataclass
class Context:
    settings: Settings
    conn: psycopg.Connection
    store: RawStore
    client: OpenF1Client | None
    run_id: object
    fixed_now: datetime | None = None  # hidden --now, to test the live-window guard
    counts: Counter = field(default_factory=Counter)

    def now(self) -> datetime:
        return self.fixed_now or datetime.now(UTC)


class StopRun(Exception):
    """A planned, clean stop: the run ends with this outcome, unfinished units stay pending/deferred."""

    def __init__(self, outcome: str, message: str):
        super().__init__(message)
        self.outcome = outcome


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


def in_settling_window(race: dict, now: datetime, settling_days: int) -> bool:
    """Recent races are re-fetched on every run: OpenF1 may still publish or correct data."""
    return now - race["date_end"] <= timedelta(days=settling_days)


def metadata_units(store: RawStore, years: tuple[int, ...]) -> list[Unit]:
    return [
        Unit(e.name, year, "all", {"year": year}, store.unit_dir(e.name, year), None)
        for year in years
        for e in endpoints.METADATA
    ]


def race_units(
    store: RawStore, race: dict, sessions: list[dict], names: tuple[str, ...]
) -> list[Unit]:
    """The session-level units of one race (drivers first, registry order)."""
    key, meeting = race["session_key"], race["meeting_key"]
    units = []
    for e in endpoints.RACE_LEVEL:
        if names and e.name not in names:
            continue
        queried = key
        if e.kind == "grid":
            queried = discovery.qualifying_key(sessions, meeting)
        params = {"session_key": queried} if queried is not None else None
        raw_dir = store.unit_dir(e.name, race["year"], meeting, key)
        units.append(
            Unit(e.name, key, "all", params, raw_dir, race["date_end"], queried)
        )
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
            key,
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
            settling_days=ctx.settings.settling_days,
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
                    "queried_session_key": unit.queried_session_key,
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
    """Run planned units in order; stops cleanly on --max-requests or when the API goes live."""
    for i, unit in enumerate(units):
        if max_requests is not None and ctx.client.requests_made >= max_requests:
            raise StopRun("partial", f"--max-requests {max_requests} reached")
        live = discovery.live_session(sessions, ctx.now())
        if live:
            # The API is blocked until the window ends: postpone everything left in this plan.
            reason = (
                f"live window of session {live['session_key']} ({live['session_name']})"
            )
            state.defer(ctx.conn, [u.id for u in units[i:]], reason)
            ctx.counts["deferred"] += len(units) - i
            raise StopRun("stopped_live_window", f"API is live: {reason}")
        run_unit(ctx, unit, sessions)


def refresh_metadata(ctx: Context, years: tuple[int, ...]) -> list[dict]:
    """Full refresh of meetings + sessions per year (the only requests made on every run); returns all sessions."""
    sessions = discovery.load_sessions(ctx.conn)
    live = discovery.live_session(sessions, ctx.now())
    if live:
        # Planning continues on the metadata loaded earlier; the runner then defers the planned units.
        log.warning(
            "API is live (session %s), metadata refresh skipped", live["session_key"]
        )
        return sessions
    units = metadata_units(ctx.store, years)
    for unit in units:
        state.set_pending(ctx.conn, *unit.id)
    execute(ctx, units, sessions, None)
    for unit in units:
        ingest.load_partition(ctx.conn, ctx.store, unit.endpoint, unit.key, ctx.run_id)
    return discovery.load_sessions(ctx.conn)


def extract(
    ctx: Context,
    filters: Filters,
    force: bool = False,
    max_requests: int | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Refresh metadata, then plan and fetch every eligible race. Returns the dry-run plan lines."""
    sessions = refresh_metadata(ctx, filters.years or ctx.settings.scope_years)
    races = discovery.eligible_races(
        sessions, ctx.now(), ctx.settings.scope_years, filters
    )
    want_car_data = not filters.endpoints or "car_data" in filters.endpoints
    log.info("%d eligible races", len(races))
    plan_lines = []

    for race in races:
        key = race["session_key"]
        reset = force or in_settling_window(race, ctx.now(), ctx.settings.settling_days)
        statuses = state.unit_statuses(ctx.conn, key)
        units = units_to_run(
            race_units(ctx.store, race, sessions, filters.endpoints), statuses, reset
        )

        if dry_run:
            plan_lines.append(
                _dry_run_line(ctx, race, units, statuses, reset, want_car_data)
            )
            continue

        for unit in units:
            state.set_pending(ctx.conn, *unit.id)
        execute(ctx, units, sessions, max_requests)

        if want_car_data:
            # car_data is planned only once this race's driver list is known.
            statuses = state.unit_statuses(ctx.conn, key)
            if statuses.get(("drivers", "all")) != "done":
                log.info("%s: drivers not done, car_data not planned", key)
                continue
            drivers = ctx.store.read_records(
                ctx.store.unit_dir("drivers", race["year"], race["meeting_key"], key)
            )
            units = units_to_run(
                car_data_units(ctx.store, race, drivers), statuses, reset
            )
            for unit in units:
                state.set_pending(ctx.conn, *unit.id)
            execute(ctx, units, sessions, max_requests)
    return plan_lines


def _dry_run_line(ctx, race, units, statuses, reset, want_car_data) -> str:
    car_data = "0"
    if want_car_data:
        if statuses.get(("drivers", "all")) == "done":
            drivers = ctx.store.read_records(
                ctx.store.unit_dir(
                    "drivers", race["year"], race["meeting_key"], race["session_key"]
                )
            )
            car_data = str(
                len(
                    units_to_run(
                        car_data_units(ctx.store, race, drivers), statuses, reset
                    )
                )
            )
        else:
            car_data = f"~{CAR_DATA_ESTIMATE}"
    names = ",".join(u.endpoint for u in units) or "-"
    return (
        f"{race['date_start']:%Y-%m-%d} race {race['session_key']}: "
        f"{len(units)} units ({names}), car_data {car_data}"
    )
