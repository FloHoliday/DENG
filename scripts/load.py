"""Step 3, load: load the complete sessions (_SUCCESS) of one meeting, or of all of data/raw, into the typed PostgreSQL tables."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from upath import UPath

import load

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--meeting-key",
        type=int,
        help="OpenF1 meeting_key of the race weekend to load, default: every meeting in --raw-dir",
    )
    parser.add_argument(
        "--raw-dir",
        type=UPath,
        default=UPath("data/raw"),
        help="local path or gs://bucket/path, default: data/raw",
    )
    args = parser.parse_args()
    failed = load.run(args.raw_dir, args.meeting_key)
    if failed:
        sys.exit(f"{failed} sessions failed to load, see the errors above")
