"""Ingest + store: fetch the OpenF1 data of all race weekends since a date into raw JSON files, then load them into PostgreSQL."""

import argparse
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import fetch
import ingest

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        required=True,
        help="ingest all race weekends starting on or after this date, e.g. 2025-01-01",
    )
    parser.add_argument(
        "--raw-dir", type=Path, default=Path("data/raw"), help="default: data/raw"
    )
    parser.add_argument(
        "-f", "--force", action="store_true", help="re-fetch existing files"
    )
    args = parser.parse_args()

    failed = fetch.run(
        args.since,
        args.raw_dir,
        access_token=os.environ.get("OPENF1_ACCESS_TOKEN"),
        force=args.force,
    )
    # Complete sessions are loaded even if others failed, those follow on the next run.
    ingest.run(args.raw_dir)
    if failed:
        sys.exit(f"{failed} sessions failed, re-run to resume")
