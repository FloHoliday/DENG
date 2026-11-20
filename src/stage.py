"""Per-race build of the silver and gold stages: build → check → publish, then bookmark.

Every SQL file in sql/<stage>/ (named NN_<table>.sql, run in name order) is one SELECT
that becomes the table <table>; later files can read earlier ones as temp views. Only
races built in the stage before more recently than here are rebuilt, each one on its own:
a race that fails its build or its checks publishes nothing and gets no bookmark, so the
next run retries it; all other races are still built (W4).
"""

import sys
from collections.abc import Callable
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession

from checks import Check, report
from spark import lake

SQL_DIR = Path(__file__).parents[1] / "sql"
# <stage>/built_sessions: when each session (bronze) or race was last built successfully.
BOOKMARK_SCHEMA = "session_key INT NOT NULL, built_at TIMESTAMP NOT NULL"


def path(stage: str, table: str) -> str:
    return str(lake(stage, table))


def ensure_table(spark: SparkSession, table_path: str, schema: str) -> None:
    spark.sql(f"CREATE TABLE IF NOT EXISTS delta.`{table_path}` ({schema}) USING DELTA")


def read(spark: SparkSession, stage: str, table: str) -> DataFrame:
    return spark.read.format("delta").load(path(stage, table))


def replace(df: DataFrame, table_path: str, predicate: str) -> None:
    """Replace the rows matching `predicate` with `df` in one Delta commit."""
    (
        df.coalesce(1)  # one file per race and table; data skipping finds it by min/max
        .write.format("delta")
        .mode("overwrite")
        .option("replaceWhere", predicate)
        .save(table_path)
    )


def publish(df: DataFrame, stage: str, table: str, session_key: int) -> None:
    """Write one race of one table. shortcut: gold goes to local Delta too, switch it to BigQuery (O6) once GCP is available."""
    replace(df, path(stage, table), f"session_key = {session_key}")


def bookmarks(spark: SparkSession, stage: str) -> DataFrame:
    table_path = path(stage, "built_sessions")
    ensure_table(spark, table_path, BOOKMARK_SCHEMA)
    return spark.read.format("delta").load(table_path)


def set_bookmark(spark: SparkSession, stage: str, session_key: int) -> None:
    """Written after all of a session's tables, so one that fails half-way is built again."""
    row = spark.range(1).selectExpr(
        f"CAST({int(session_key)} AS INT) AS session_key",
        "current_timestamp() AS built_at",
    )
    replace(row, path(stage, "built_sessions"), f"session_key = {session_key}")


def todo(spark: SparkSession, stage: str, upstream: DataFrame) -> list:
    """Races of `upstream` (session_key, built_at) built there after their last build here."""
    built = bookmarks(spark, stage).withColumnRenamed("built_at", "own_built_at")
    return (
        upstream.join(built, "session_key", "left")
        .where("own_built_at IS NULL OR built_at > own_built_at")
        .select("session_key")
        .orderBy("session_key")
        .collect()
    )


def drop_stage(stage: str) -> None:
    """Delete every table of the stage, so a changed definition (new columns) is rebuilt."""
    stage_dir = lake(stage)
    if stage_dir.exists():
        stage_dir.fs.rm(stage_dir.path, recursive=True)
        print(f"full refresh: deleted {stage_dir}")


def build_race(
    spark: SparkSession,
    stage: str,
    session_key: int,
    view_prefix: str,
    checks: Callable[[SparkSession], list[Check]],
) -> None:
    """Run the stage's SQL for one race (inputs already registered as temp views)."""
    frames = {}
    try:
        for sql_file in sorted((SQL_DIR / stage).glob("*.sql")):
            table = sql_file.stem.split("_", 1)[1]
            df = spark.sql(sql_file.read_text(encoding="utf-8")).cache()
            df.createOrReplaceTempView(f"{view_prefix}{table}")
            frames[table] = df
        if report(f"{stage} {session_key}", checks(spark)):
            raise ValueError("checks failed, nothing published for this race")
        for table, df in frames.items():
            publish(df, stage, table, session_key)
    finally:
        for df in frames.values():
            df.unpersist()


def run(
    spark: SparkSession,
    stage: str,
    upstream: DataFrame,
    register_inputs: Callable[[SparkSession, int], None],
    view_prefix: str,
    checks: Callable[[SparkSession], list[Check]],
    full_refresh: bool = False,
) -> int:
    """Build every race that is newer in `upstream`; returns the number of races that failed."""
    if full_refresh:
        drop_stage(stage)
    races = todo(spark, stage, upstream)
    print(f"{stage}: {len(races)} races to build")
    failed = 0
    for race in races:
        try:
            register_inputs(spark, race.session_key)
            build_race(spark, stage, race.session_key, view_prefix, checks)
        except Exception as exc:  # noqa: BLE001 - report the race, build the others
            error = str(exc).splitlines()[0][:1000]
            print(f"FAILED {stage} {race.session_key}: {error}", file=sys.stderr)
            failed += 1
            continue
        set_bookmark(spark, stage, race.session_key)
        print(f"built {stage} {race.session_key}")
    print(f"{stage}: {len(races) - failed} races built, {failed} failed")
    return failed
