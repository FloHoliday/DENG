"""Step 4, silver: clean and conform the bronze data of every new or reloaded race."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import silver
import spark as lakehouse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="delete silver and rebuild every race (needed after changing sql/silver/)",
    )
    args = parser.parse_args()
    spark = lakehouse.session("silver")
    failed = silver.run(spark, args.full_refresh)
    spark.stop()
    if failed:
        sys.exit(f"{failed} races failed, see the errors above")
