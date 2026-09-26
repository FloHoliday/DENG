"""Fetch the raw OpenF1 data for one race weekend and save it unchanged as JSON."""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "https://api.openf1.org/v1"
MIN_REQUEST_INTERVAL = 0.34  # API limit: 3 requests/second
MAX_ATTEMPTS = 5
TIMEOUT = 60

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
    def __init__(self) -> None:
        self._http = requests.Session()
        self._last_request = 0.0

    def get(self, endpoint: str, **params) -> list[dict]:
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
                    sys.exit(f"OpenF1 access denied: {resp.json().get('detail', resp.text)}")
                if resp.status_code == 429 or resp.status_code >= 500:
                    error = f"HTTP {resp.status_code}"
                else:
                    resp.raise_for_status()
                    return resp.json()

            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(f"{endpoint} {params}: {error} after {attempt} attempts")
            backoff = 2 ** attempt
            print(f"{endpoint} {params}: {error}, retrying in {backoff}s", file=sys.stderr)
            time.sleep(backoff)
        raise AssertionError("unreachable")


def resolve_meeting(client: OpenF1Client, args: argparse.Namespace) -> dict:
    if args.meeting_key is not None:
        meetings = client.get("meetings", meeting_key=args.meeting_key)
        if not meetings:
            sys.exit(f"No meeting found with meeting_key={args.meeting_key}")
        return meetings[0]

    meetings = client.get("meetings", year=args.year)
    if not meetings:
        sys.exit(f"No meetings found for {args.year}")
    if args.meeting is None:
        return select_meeting(meetings, f"Meetings in {args.year}:")

    needle = args.meeting.lower()
    fields = ("meeting_name", "location", "country_name", "circuit_short_name")
    matches = [
        m for m in meetings if any(needle in str(m.get(f, "")).lower() for f in fields)
    ]
    if len(matches) == 1:
        return matches[0]
    if matches:
        header = f"Multiple meetings matched '{args.meeting}' in {args.year}:"
    else:
        header = f"No meeting matched '{args.meeting}' in {args.year}. All meetings:"
        matches = meetings
    return select_meeting(matches, header)


def select_meeting(meetings: list[dict], header: str) -> dict:
    """Let the user pick one of `meetings` interactively."""
    print(header)
    for i, m in enumerate(meetings, 1):
        print(f"  [{i:2d}] {m['date_start'][:10]}  {m['meeting_name']} ({m['location']}, key {m['meeting_key']})")
    if not sys.stdin.isatty():
        sys.exit("Not running interactively; use a more specific name or --meeting-key.")

    while True:
        try:
            choice = input(f"Select a meeting [1-{len(meetings)}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit("\nAborted.")
        if choice.isdigit() and 1 <= int(choice) <= len(meetings):
            return meetings[int(choice) - 1]
        print("Invalid choice, try again.")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def write_json(path: Path, data: list | dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)


def fetch_to_file(client: OpenF1Client, path: Path, force: bool, endpoint: str, **params) -> int:
    """Fetch one endpoint into `path` and return its row count."""
    if path.exists() and not force:
        rows = len(json.loads(path.read_text(encoding="utf-8")))
        print(f"skip  {path.name:<40} {rows:6d} rows (exists)")
        return rows
    start = time.monotonic()
    data = client.get(endpoint, **params)
    write_json(path, data)
    print(f"fetch {path.name:<40} {len(data):6d} rows in {time.monotonic() - start:.1f}s")
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
        sessions: list[dict],
        meeting_dir: Path,
        args: argparse.Namespace,
) -> bool:
    session_key = session["session_key"]
    session_dir = meeting_dir / f"{session_key}_{slug(session['session_name'])}"
    print(f"== {session['session_name']} (session_key={session_key}) -> {session_dir}")

    counts: dict[str, int] = {}
    failed = False
    for endpoint in SESSION_ENDPOINTS:
        try:
            counts[endpoint] = fetch_to_file(
                client, session_dir / f"{endpoint}.json", args.force, endpoint,
                session_key=session_key,
            )
        except Exception as exc:
            print(f"FAILED {endpoint}: {exc}", file=sys.stderr)
            failed = True

    grid_session = next(
        (s for s in sessions if s["session_name"] in GRID_SESSION_NAMES[session["session_name"]]),
        None,
    )
    if grid_session is None:
        print("FAILED starting_grid: no qualifying session found", file=sys.stderr)
        failed = True
    else:
        try:
            counts["starting_grid"] = fetch_to_file(
                client, session_dir / "starting_grid.json", args.force, "starting_grid",
                session_key=grid_session["session_key"],
            )
        except Exception as exc:
            print(f"FAILED starting_grid: {exc}", file=sys.stderr)
            failed = True

    if session["session_name"] == TELEMETRY_SESSION and not args.skip_telemetry:
        if "drivers" in counts:
            try:
                counts |= fetch_car_data(client, session_dir, session_key, args.force)
            except Exception as exc:
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
        {"completed_at": datetime.now(timezone.utc).isoformat(), "row_counts": counts},
    )
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-y", "--year", type=int, help="season year, e.g. 2025")
    parser.add_argument(
        "--meeting",
        help="meeting to match (case-insensitive substring of meeting name, "
             "location, country or circuit), e.g. 'monza'. If omitted, pick from a list",
    )
    parser.add_argument("--meeting-key", type=int, help="OpenF1 meeting_key, e.g. 1268")
    parser.add_argument("--skip-telemetry", action="store_true", help="do not fetch car_data")
    parser.add_argument(
        "--out-dir", type=Path, default=Path("data/raw"), help="default: data/raw"
    )
    parser.add_argument("-f", "--force", action="store_true", help="re-fetch existing files")
    args = parser.parse_args()

    if (args.meeting_key is None) == (args.year is None):
        parser.error("One of --meeting-key or --year is required, but they cannot be combined")

    client = OpenF1Client()

    meeting = resolve_meeting(client, args)
    meeting_dir = (
            args.out_dir
            / str(meeting["year"])
            / f"{meeting['meeting_key']}_{slug(meeting['location'])}"
    )
    print(f"Meeting: {meeting['year']} {meeting['meeting_name']} (meeting_key={meeting['meeting_key']})")

    sessions = client.get("sessions", meeting_key=meeting["meeting_key"])
    write_json(meeting_dir / "meeting.json", meeting)
    write_json(meeting_dir / "sessions.json", sessions)

    selected = [
        s for s in sessions if s["session_name"] in SESSION_NAMES and not s.get("is_cancelled")
    ]
    if not selected:
        sys.exit("No Race/Sprint sessions found for this meeting")

    results = [fetch_session(client, s, sessions, meeting_dir, args) for s in selected]
    if not all(results):
        sys.exit(f"{results.count(False)} of {len(results)} sessions failed")

    print(f"Done: {len(results)} sessions fetched into {meeting_dir}")
