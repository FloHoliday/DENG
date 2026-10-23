"""Step 2, fetch: download the raw OpenF1 data of one race weekend into JSON files (data/raw)."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from upath import UPath

import fetch

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--meeting-key",
        type=int,
        required=True,
        help="OpenF1 meeting_key of the race weekend, as found by check_source.py",
    )
    parser.add_argument(
        "--raw-dir",
        type=UPath,
        default=UPath("data/raw"),
        help="local path or gs://bucket/path, default: data/raw",
    )
    parser.add_argument(
        "-f", "--force", action="store_true", help="re-fetch existing files"
    )
    args = parser.parse_args()

    failed = fetch.run(args.meeting_key, args.raw_dir, force=args.force)
    # Fail fast: nothing is loaded until every session is complete; a re-run resumes.
    if failed:
        sys.exit(f"{failed} sessions failed, re-run to resume")
