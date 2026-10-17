"""Step 4, transform: rebuild the staging, core and mart models from sql/transform/ in PostgreSQL."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import transform

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="also rebuild the incremental telemetry table from scratch",
    )
    args = parser.parse_args()
    transform.run(full_refresh=args.full_refresh)
