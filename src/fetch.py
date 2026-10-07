"""Ingest step: fetch the raw OpenF1 data of all race weekends since a date and save it unchanged as JSON."""

import json
import re
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

import requests

BASE_URL = "https://api.openf1.org/v1"
MIN_REQUEST_INTERVAL = 0.5  # API limit: up to 3 requests/second & 30 requests/minute
MAX_ATTEMPTS = 5
TIMEOUT = 60
# Errors that mark a single fetch as failed without aborting the whole run.
FETCH_ERRORS = (requests.RequestException, RuntimeError)

SESSION_NAMES = {"Race", "Sprint"}
SESSION_ENDPOINTS = [
    "drivers",
    "laps",
    "stints",
    "pit",
    "position",
    "race_control",
    "session_result",
    "weather",
    "intervals",
]
TELEMETRY_SESSION = "Race"
# OpenF1 stores the starting grid under the qualifying session that set it.
GRID_SESSION_NAMES = {
    "Race": ("Qualifying",),
    "Sprint": ("Sprint Qualifying", "Sprint Shootout"),
}


class OpenF1Client:
    def __init__(self, access_token: str | None = None) -> None:
        self._http = requests.Session()
        if access_token:
            self._http.headers["Authorization"] = f"Bearer {access_token}"
        self._last_request = 0.0

    def get(self, endpoint: str, params: dict) -> list[dict]:
        url = f"{BASE_URL}/{endpoint}"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            wait = self._last_request + MIN_REQUEST_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

            try:
                resp = self._http.get(url, params=params, timeout=TIMEOUT)
            except (requests.ConnectionError, requests.Timeout) as exc:
                error = str(exc)
            else:
                if resp.status_code == 404:
                    return []
                if resp.status_code == 401:
                    # During live F1 sessions the whole API requires an API key.
                    sys.exit(
                        f"OpenF1 access denied: {resp.json().get('detail', resp.text)}"
                    )
                if resp.status_code in (422, 429) or resp.status_code >= 500:
                    error = f"HTTP {resp.status_code}"
                else:
                    resp.raise_for_status()
                    return resp.json()

            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(
                    f"{endpoint} {params}: {error} after {attempt} attempts"
                )
            backoff = 2**attempt
            print(
                f"{endpoint} {params}: {error}, retrying in {backoff}s", file=sys.stderr
            )
            time.sleep(backoff)
        raise AssertionError("unreachable")


def find_meetings(client: OpenF1Client, since: date) -> list[dict]:
    """Non-cancelled meetings starting on or after `since`."""
    today = datetime.now(UTC).date()
    return client.get(
        "meetings", {"date_start>": since, "date_end<": today, "is_cancelled": False}
    )


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def write_json(path: Path, data: list | dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)


def fetch_to_file(
    client: OpenF1Client, path: Path, force: bool, endpoint: str, **params
) -> int:
    """Fetch one endpoint into `path` and return its row count."""
    if path.exists() and not force:
        rows = len(json.loads(path.read_text(encoding="utf-8")))
        print(f"skip  {path.name:<40} {rows:6d} rows (exists)")
        return rows
    start = time.monotonic()
    data = client.get(endpoint, params)
    write_json(path, data)
    print(
        f"fetch {path.name:<40} {len(data):6d} rows in {time.monotonic() - start:.1f}s"
    )
    return len(data)


def fetch_car_data(
    client: OpenF1Client, session_dir: Path, session_key: int, force: bool
) -> dict[str, int]:
    drivers = json.loads((session_dir / "drivers.json").read_text(encoding="utf-8"))
    counts = {}
    for driver_number in sorted({d["driver_number"] for d in drivers}):
        name = f"car_data/driver_{driver_number}"
        counts[name] = fetch_to_file(
            client,
            session_dir / f"{name}.json",
            force,
            "car_data",
            session_key=session_key,
            driver_number=driver_number,
        )
    return counts


def fetch_session(
    client: OpenF1Client,
    session: dict,
    meeting_dir: Path,
    force: bool,
) -> bool:
    session_key = session["session_key"]
    session_dir = meeting_dir / f"{session_key}_{slug(session['session_name'])}"
    print(f"== {session['session_name']} (session_key={session_key}) -> {session_dir}")
    # Keep the marker unchanged so the store step doesn't reload the session.
    if (session_dir / "_SUCCESS").exists() and not force:
        print("skip  session (complete)")
        return True

    counts: dict[str, int] = {}
    failed = False
    for endpoint in SESSION_ENDPOINTS:
        try:
            counts[endpoint] = fetch_to_file(
                client,
                session_dir / f"{endpoint}.json",
                force,
                endpoint,
                session_key=session_key,
            )
        except FETCH_ERRORS as exc:
            print(f"FAILED {endpoint}: {exc}", file=sys.stderr)
            failed = True

    try:
        grid_sessions = client.get(
            "sessions",
            {
                "meeting_key": session["meeting_key"],
                "session_name": GRID_SESSION_NAMES[session["session_name"]],
            },
        )
        if not grid_sessions:
            print("FAILED starting_grid: no qualifying session found", file=sys.stderr)
            failed = True
        else:
            counts["starting_grid"] = fetch_to_file(
                client,
                session_dir / "starting_grid.json",
                force,
                "starting_grid",
                session_key=grid_sessions[0]["session_key"],
            )
    except FETCH_ERRORS as exc:
        print(f"FAILED starting_grid: {exc}", file=sys.stderr)
        failed = True

    if session["session_name"] == TELEMETRY_SESSION:
        if "drivers" in counts:
            try:
                counts |= fetch_car_data(client, session_dir, session_key, force)
            except FETCH_ERRORS as exc:
                print(f"FAILED car_data: {exc}", file=sys.stderr)
                failed = True
        else:
            print("FAILED car_data: drivers list unavailable", file=sys.stderr)
            failed = True

    if failed:
        print(f"Session {session_key} incomplete, no _SUCCESS written", file=sys.stderr)
        return False
    write_json(
        session_dir / "_SUCCESS",
        {"completed_at": datetime.now(UTC).isoformat(), "row_counts": counts},
    )
    return True


def fetch_meeting(
    client: OpenF1Client,
    meeting: dict,
    raw_dir: Path,
    force: bool,
) -> list[bool]:
    """Fetch the meeting metadata and the `selected` sessions; one result per session."""
    try:
        sessions = client.get(
            "sessions",
            {"meeting_key": meeting["meeting_key"], "session_name": SESSION_NAMES},
        )
    except FETCH_ERRORS as exc:
        print(f"FAILED meeting {meeting['meeting_key']}: {exc}", file=sys.stderr)
        return [False] * len(SESSION_NAMES)

    meeting_dir = (
        raw_dir
        / str(meeting["year"])
        / f"{meeting['meeting_key']}_{slug(meeting['location'])}"
    )
    print(
        f"Meeting: {meeting['year']} {meeting['meeting_name']} (meeting_key={meeting['meeting_key']})"
    )
    write_json(meeting_dir / "meeting.json", meeting)
    write_json(meeting_dir / "sessions.json", sessions)

    return [fetch_session(client, s, meeting_dir, force) for s in sessions]


def run(
    since: date,
    raw_dir: Path = Path("data/raw"),
    access_token: str | None = None,
    force: bool = False,
) -> int:
    """Fetch all race weekends since `since` into `raw_dir`; returns the number of failed sessions."""
    client = OpenF1Client(access_token)

    meetings = find_meetings(client, since)
    if not meetings:
        sys.exit(f"No meetings found since {since}")

    results = []
    for meeting in meetings:
        results += fetch_meeting(client, meeting, raw_dir, force)
    print(
        f"Fetched {results.count(True)} of {len(results)} sessions from {len(meetings)} meetings into {raw_dir}"
    )
    return results.count(False)
