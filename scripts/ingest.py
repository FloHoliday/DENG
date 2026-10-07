"""Ingest + store with dlt: fetch the OpenF1 data of all race weekends since a date into raw files, then load them into PostgreSQL staging tables."""

import argparse
import os
from datetime import date
from pathlib import Path

from pipelines import fetch, ingest

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        required=True,
        help="ingest all race weekends starting after this date, e.g. 2025-01-01 (first run only)",
    )
    parser.add_argument(
        "--raw-dir", type=Path, default=Path("data/raw"), help="default: data/raw"
    )
    args = parser.parse_args()

    fetch.run(
        args.since,
        args.raw_dir,
        access_token=os.environ.get("OPENF1_ACCESS_TOKEN"),
    )
    ingest.run(args.raw_dir)
