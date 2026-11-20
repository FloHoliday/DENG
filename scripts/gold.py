"""Step 5, gold: build the facts and the mart of every race whose silver data changed."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import gold
import spark as lakehouse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="delete gold and rebuild every race (needed after changing sql/gold/)",
    )
    args = parser.parse_args()
    spark = lakehouse.session("gold")
    failed = gold.run(spark, args.full_refresh)
    spark.stop()
    if failed:
        sys.exit(f"{failed} races failed, see the errors above")
