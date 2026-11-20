"""Step 3, bronze: load the complete sessions (_SUCCESS) of one meeting, or of all of <LAKE_URI>/raw, into typed Delta tables."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import bronze
import spark as lakehouse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--meeting-key",
        type=int,
        help="OpenF1 meeting_key of the race weekend to load, default: every meeting in raw/",
    )
    args = parser.parse_args()

    spark = lakehouse.session("bronze")
    failed = bronze.run(spark, lakehouse.lake("raw"), args.meeting_key)
    spark.stop()
    if failed:
        sys.exit(f"{failed} sessions failed to load, see the errors above")
