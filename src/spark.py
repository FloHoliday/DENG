"""Spark session and lake paths shared by the bronze, silver and gold steps."""

import os

from delta import configure_spark_with_delta_pip
from pyspark.sql import SparkSession
from upath import UPath

# Root of the lake: a local folder (default `data`, the deng_raw_data volume in Docker)
# or gs://<bucket> once GCP is available. raw/, bronze/, silver/ and gold/ sit below it.
LAKE_URI = os.environ.get("LAKE_URI", "data")


def lake(*parts: str) -> UPath:
    return UPath(LAKE_URI).joinpath(*parts)


def session(app: str) -> SparkSession:
    """A local Spark session (all executors in this process) with Delta Lake enabled."""
    builder = (
        SparkSession.builder.appName(app)
        .master("local[*]")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        # The largest input, one race's car_data, is about 0.8M rows.
        .config("spark.driver.memory", "6g")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "16")
        .config("spark.ui.enabled", "false")
        .config("spark.ui.showConsoleProgress", "false")
    )
    spark = configure_spark_with_delta_pip(builder).getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark
