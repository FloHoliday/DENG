"""Step 3, load: load every complete session (_SUCCESS) from data/raw into the typed PostgreSQL tables."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from upath import UPath

import load

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-dir",
        type=UPath,
        default=UPath("data/raw"),
        help="local path or gs://bucket/path, default: data/raw",
    )
    args = parser.parse_args()
    load.run(args.raw_dir)
