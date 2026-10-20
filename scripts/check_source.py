"""Step 1, check source: fail early if OpenF1 is unreachable or locked by a live session, and list the race weekends to fetch."""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import fetch

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        required=True,
        help="race weekends starting on or after this date, e.g. 2023-01-01",
    )
    args = parser.parse_args()
    fetch.check_source(args.since)
