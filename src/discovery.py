"""Which races to extract, the qualifying session for the grid, and whether the API is live (blocked)."""

from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg
from psycopg.rows import dict_row

# OpenF1 serves data as "live" (paid only) from 30 min before a session until 30 min after it.
LIVE_MARGIN = timedelta(minutes=30)


@dataclass(frozen=True)
class Filters:
    years: tuple[int, ...] = ()
    meeting_key: int | None = None
    session_key: int | None = None
    endpoints: tuple[str, ...] = ()


def load_sessions(conn: psycopg.Connection) -> list[dict]:
    """All sessions (every type) from the loaded metadata; a session counts as cancelled if its meeting is."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute("""
            SELECT s.session_key, s.meeting_key, s.session_name, s.year, s.date_start, s.date_end,
                   coalesce(s.is_cancelled, false) OR coalesce(m.is_cancelled, false) AS is_cancelled
            FROM raw.sessions s
            LEFT JOIN raw.meetings m ON m.meeting_key = s.meeting_key
            ORDER BY s.date_start
        """).fetchall()


def eligible_races(
    sessions: list[dict], now: datetime, scope_years: tuple[int, ...], filters: Filters
) -> list[dict]:
    """Finished, non-cancelled Race sessions in scope, oldest first.

    Selects on session_name: the Sprint also has session_type 'Race'.
    """
    years = filters.years or scope_years
    races = [
        s
        for s in sessions
        if s["session_name"] == "Race"
        and not s["is_cancelled"]
        and s["date_end"] is not None
        and s["date_end"] + LIVE_MARGIN < now
        and s["year"] in years
        and filters.meeting_key in (None, s["meeting_key"])
        and filters.session_key in (None, s["session_key"])
    ]
    return sorted(races, key=lambda s: s["date_start"])


def qualifying_key(sessions: list[dict], meeting_key: int) -> int | None:
    for s in sessions:
        if s["meeting_key"] == meeting_key and s["session_name"] == "Qualifying":
            return s["session_key"]
    return None


def live_session(sessions: list[dict], now: datetime) -> dict | None:
    """The session whose live window contains `now`, if any (both boundaries inclusive)."""
    for s in sessions:
        if s["is_cancelled"] or s["date_start"] is None or s["date_end"] is None:
            continue
        if s["date_start"] - LIVE_MARGIN <= now <= s["date_end"] + LIVE_MARGIN:
            return s
    return None
