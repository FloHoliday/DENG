"""Step 2, find race: output the meeting_key of the race in the 7 days before a date (null if none)."""

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import fetch

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=datetime.now(UTC).date(),
        help="look for a race in the 7 days before this date, default: today",
    )
    args = parser.parse_args()
    if args.date > datetime.now(UTC).date():
        sys.exit(f"--date {args.date} is in the future")
    race = fetch.find_race(args.date)
    meeting_key = race["meeting_key"] if race else None
    print("::" + json.dumps({"outputs": {"meeting_key": meeting_key}}) + "::")
