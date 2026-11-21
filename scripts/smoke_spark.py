"""Smoke test of the Spark image: write, overwrite and read back a Delta table in the lake.

Also run once by `docker build`, so the Delta jars are downloaded into the image.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from deng_f1 import spark as lakehouse

if __name__ == "__main__":
    spark = lakehouse.session("smoke")
    with tempfile.TemporaryDirectory() as tmp:
        path = f"{tmp}/smoke"
        spark.range(3).write.format("delta").save(path)
        spark.range(5).write.format("delta").mode("overwrite").save(path)
        rows = spark.read.format("delta").load(path).count()
        versions = spark.sql(f"DESCRIBE HISTORY delta.`{path}`").count()
        assert (rows, versions) == (5, 2), (rows, versions)
    print(f"Spark {spark.version} with Delta Lake works")
    spark.stop()
