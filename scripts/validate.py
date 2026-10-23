"""Step 5, validate: check that the database matches data/raw and the models are complete; exits 1 on any failed check."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from upath import UPath

import validate

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--meeting-key",
        type=int,
        help="also check that this meeting's race is loaded; compare only its sessions with data/raw",
    )
    parser.add_argument(
        "--raw-dir",
        type=UPath,
        default=UPath("data/raw"),
        help="local path or gs://bucket/path, default: data/raw",
    )
    args = parser.parse_args()
    failed = validate.run(args.raw_dir, args.meeting_key)
    if failed:
        sys.exit(f"{failed} checks failed")
