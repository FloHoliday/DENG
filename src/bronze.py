"""Bronze step: load the raw JSON of every complete race session into typed Delta tables.

One Delta table per endpoint under <LAKE_URI>/bronze/. A session is checked first and
then replaces its own rows (replaceWhere), so other races are never touched. The table
schema is enforced on write: a new, renamed or wrongly typed field fails the session.
"""

import json
import sys

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StructType
from upath import UPath

from checks import Check, duplicates, report, sql_check
from fetch import SESSION_ENDPOINTS
from spark import lake

# One typed column per OpenF1 field (from the v0.2 PostgreSQL schema). meetings and
# sessions are replaced per meeting_key; all other tables per (Race) session_key.
SCHEMAS = {
    "meetings": """
        circuit_key INT, circuit_image STRING, circuit_info_url STRING,
        circuit_short_name STRING, circuit_type STRING, country_code STRING,
        country_flag STRING, country_key INT, country_name STRING,
        date_end TIMESTAMP NOT NULL, date_start TIMESTAMP NOT NULL, gmt_offset STRING,
        is_cancelled BOOLEAN, location STRING, meeting_key INT NOT NULL,
        meeting_name STRING NOT NULL, meeting_official_name STRING, year INT NOT NULL
    """,
    "sessions": """
        circuit_key INT, circuit_short_name STRING, country_code STRING, country_key INT,
        country_name STRING, date_end TIMESTAMP NOT NULL, date_start TIMESTAMP NOT NULL,
        gmt_offset STRING, is_cancelled BOOLEAN, location STRING,
        meeting_key INT NOT NULL, session_key INT NOT NULL, session_name STRING NOT NULL,
        session_type STRING, year INT NOT NULL
    """,
    "drivers": """
        broadcast_name STRING, country_code STRING, driver_number INT NOT NULL,
        first_name STRING, full_name STRING, headshot_url STRING, last_name STRING,
        meeting_key INT NOT NULL, name_acronym STRING, session_key INT NOT NULL,
        team_colour STRING, team_name STRING
    """,
    "laps": """
        date_start TIMESTAMP, driver_number INT NOT NULL, duration_sector_1 DOUBLE,
        duration_sector_2 DOUBLE, duration_sector_3 DOUBLE, i1_speed INT, i2_speed INT,
        is_pit_out_lap BOOLEAN, lap_duration DOUBLE, lap_number INT NOT NULL,
        meeting_key INT NOT NULL, segments_sector_1 ARRAY<INT>,
        segments_sector_2 ARRAY<INT>, segments_sector_3 ARRAY<INT>,
        session_key INT NOT NULL, st_speed INT
    """,
    "stints": """
        compound STRING, driver_number INT NOT NULL, lap_end INT, lap_start INT,
        meeting_key INT NOT NULL, session_key INT NOT NULL, stint_number INT NOT NULL,
        tyre_age_at_start INT
    """,
    # pit_duration is deprecated (same as lane_duration); stop_duration only from the 2024 US GP.
    "pit": """
        date TIMESTAMP NOT NULL, driver_number INT NOT NULL, lane_duration DOUBLE,
        lap_number INT, meeting_key INT NOT NULL, pit_duration DOUBLE,
        session_key INT NOT NULL, stop_duration DOUBLE
    """,
    "position": """
        date TIMESTAMP NOT NULL, driver_number INT NOT NULL, meeting_key INT NOT NULL,
        position INT NOT NULL, session_key INT NOT NULL
    """,
    "race_control": """
        category STRING, date TIMESTAMP NOT NULL, driver_number INT, flag STRING,
        lap_number INT, meeting_key INT NOT NULL, message STRING, qualifying_phase INT,
        scope STRING, sector INT, session_key INT NOT NULL
    """,
    # gap_to_leader / interval are seconds or text like '+1 LAP', so they stay STRING.
    "session_result": """
        dnf BOOLEAN, dns BOOLEAN, dsq BOOLEAN, driver_number INT NOT NULL,
        duration DOUBLE, gap_to_leader STRING, number_of_laps INT,
        meeting_key INT NOT NULL, position INT, session_key INT NOT NULL, points DOUBLE
    """,
    "weather": """
        air_temperature DOUBLE, date TIMESTAMP NOT NULL, humidity DOUBLE,
        meeting_key INT NOT NULL, pressure DOUBLE, rainfall INT,
        session_key INT NOT NULL, track_temperature DOUBLE, wind_direction INT,
        wind_speed DOUBLE
    """,
    "intervals": """
        date TIMESTAMP NOT NULL, driver_number INT NOT NULL, gap_to_leader STRING,
        `interval` STRING, meeting_key INT NOT NULL, session_key INT NOT NULL
    """,
    # session_key is the qualifying session that set the grid, race_session_key the Race.
    "starting_grid": """
        driver_number INT NOT NULL, lap_duration DOUBLE, meeting_key INT NOT NULL,
        position INT NOT NULL, session_key INT NOT NULL
    """,
    "car_data": """
        brake INT, date TIMESTAMP NOT NULL, driver_number INT NOT NULL, drs INT,
        meeting_key INT NOT NULL, n_gear INT, rpm INT, session_key INT NOT NULL,
        speed INT, throttle INT
    """,
}
SESSION_TABLES = [*SESSION_ENDPOINTS, "starting_grid", "car_data"]
KEY_COLUMNS = {"starting_grid": "race_session_key"}
# Columns added by this step, not by OpenF1.
EXTRA_COLUMNS = {"race_session_key": "INT NOT NULL", "loaded_at": "TIMESTAMP NOT NULL"}
# Which _SUCCESS marker each session was loaded from; a newer marker means reload.
BOOKMARK = "loaded_sessions"
BOOKMARK_SCHEMA = "session_key INT NOT NULL, completed_at STRING NOT NULL, loaded_at TIMESTAMP NOT NULL"
# OpenF1 itself sends UNKNOWN for a few stints (e.g. 2024 Lusail).
COMPOUNDS = ("SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET", "UNKNOWN")


def read_json(path: UPath):
    return json.loads(path.read_text(encoding="utf-8"))


def success_markers(raw_dir: UPath, meeting_key: int | None = None) -> list[UPath]:
    """The _SUCCESS markers of one meeting (raw/<year>/<meeting_key>_<location>/), or of all."""
    pattern = f"*/{meeting_key}_*/*/_SUCCESS" if meeting_key else "**/_SUCCESS"
    return sorted(raw_dir.glob(pattern))


def table_schema(table: str) -> str:
    extra = ["race_session_key"] if table in KEY_COLUMNS else []
    columns = [SCHEMAS[table], *(f"{c} {EXTRA_COLUMNS[c]}" for c in extra)]
    return ", ".join([*columns, f"loaded_at {EXTRA_COLUMNS['loaded_at']}"])


def table_path(table: str) -> str:
    return str(lake("bronze", table))


def ensure_table(spark: SparkSession, path: str, schema: str) -> None:
    spark.sql(f"CREATE TABLE IF NOT EXISTS delta.`{path}` ({schema}) USING DELTA")


def replace(df: DataFrame, path: str, predicate: str) -> None:
    """Replace the rows matching `predicate` with `df` in one Delta commit."""
    (
        df.coalesce(1)  # one file per race and table; data skipping finds it by min/max
        .write.format("delta")
        .mode("overwrite")
        .option("replaceWhere", predicate)
        .save(path)
    )


def read_typed(spark: SparkSession, paths: list[str], table: str) -> DataFrame:
    """Read JSON files with the table's schema; an unknown field or a wrong type fails."""
    schema = StructType.fromDDL(SCHEMAS[table])
    reader = spark.read.option("multiLine", True)
    unknown = set(reader.json(paths).columns) - set(schema.names)
    if unknown:
        raise ValueError(f"{table}: unknown fields {sorted(unknown)}")
    return reader.schema(schema).option("mode", "FAILFAST").json(paths)


def session_checks(spark: SparkSession, counts: dict, expected: dict) -> list[Check]:
    """Checks on the session's DataFrames (temp views bronze_<table>) before any write."""
    checks = [
        Check(
            f"{table}: rows match _SUCCESS",
            int(counts[table] != expected[table]),
            f"{counts[table]} rows, _SUCCESS says {expected[table]}",
        )
        for table in SESSION_TABLES
    ]
    checks += [
        duplicates(spark, "bronze_laps", "driver_number, lap_number"),
        duplicates(spark, "bronze_stints", "driver_number, stint_number"),
        duplicates(spark, "bronze_pit", "driver_number, lap_number"),
        Check(
            "race has a result and a starting grid",
            int(not counts["session_result"] or not counts["starting_grid"]),
            f"{counts['session_result']} results, {counts['starting_grid']} grid rows",
        ),
        sql_check(
            spark,
            "stints: compound is a known value",
            f"""SELECT count(*), concat_ws(', ', collect_set(compound)) FROM bronze_stints
                WHERE compound NOT IN {COMPOUNDS}""",
        ),
        Check(
            "drivers: 18 to 22 per race",
            int(not 18 <= counts["drivers"] <= 22),
            f"{counts['drivers']} drivers",
            "warn",
        ),
        Check(
            "starting_grid: one position per driver",
            int(counts["starting_grid"] < counts["drivers"]),
            f"{counts['starting_grid']} grid positions, {counts['drivers']} drivers",
            "warn",
        ),
    ]
    return checks


def load_session(spark: SparkSession, session_dir: UPath, completed_at: str) -> int:
    """Check one session and replace its rows; returns the number of rows loaded."""
    success = read_json(session_dir / "_SUCCESS")
    session_key = int(session_dir.name.split("_")[0])
    meeting_dir = session_dir.parent
    meeting_key = read_json(meeting_dir / "meeting.json")["meeting_key"]
    loaded_at = F.current_timestamp()

    frames, counts, expected = {}, {}, {}
    for table in SESSION_TABLES:
        if table == "car_data":
            paths = [str(p) for p in sorted(session_dir.glob("car_data/*.json"))]
        else:
            paths = [str(session_dir / f"{table}.json")]
        key = KEY_COLUMNS.get(table, "session_key")
        df = read_typed(spark, paths, table).withColumn(key, F.lit(session_key))
        frames[table] = df.withColumn("loaded_at", loaded_at).cache()
        frames[table].createOrReplaceTempView(f"bronze_{table}")
        counts[table] = frames[table].count()
        expected[table] = sum(
            n
            for name, n in success["row_counts"].items()
            if name.split("/")[0] == table
        )
    meeting = {
        table: read_typed(spark, [str(meeting_dir / file)], table)
        .withColumn("loaded_at", loaded_at)
        .cache()
        for table, file in (("meetings", "meeting.json"), ("sessions", "sessions.json"))
    }

    try:
        if report(
            f"bronze {session_dir.name}", session_checks(spark, counts, expected)
        ):
            raise ValueError("checks failed, nothing written for this session")

        for table, df in meeting.items():
            replace(df, ensure(spark, table), f"meeting_key = {meeting_key}")
        # The bookmark is written last: a session that fails half-way is loaded again.
        for table, df in frames.items():
            key = KEY_COLUMNS.get(table, "session_key")
            replace(df, ensure(spark, table), f"{key} = {session_key}")
        bookmark = spark.createDataFrame(
            [(session_key, completed_at)], "session_key INT, completed_at STRING"
        ).withColumn("loaded_at", loaded_at)
        path = table_path(BOOKMARK)
        ensure_table(spark, path, BOOKMARK_SCHEMA)
        replace(bookmark, path, f"session_key = {session_key}")
    finally:
        for df in [*frames.values(), *meeting.values()]:
            df.unpersist()
    return sum(counts.values())


def ensure(spark: SparkSession, table: str) -> str:
    path = table_path(table)
    ensure_table(spark, path, table_schema(table))
    return path


def loaded_sessions(spark: SparkSession) -> dict[int, str]:
    """session_key -> completed_at of the _SUCCESS marker it was loaded from."""
    path = table_path(BOOKMARK)
    ensure_table(spark, path, BOOKMARK_SCHEMA)
    rows = spark.read.format("delta").load(path).collect()
    return {r.session_key: r.completed_at for r in rows}


def run(spark: SparkSession, raw_dir: UPath, meeting_key: int | None = None) -> int:
    """Load every session whose _SUCCESS marker is newer than its last load; returns the number failed.

    Only the sessions of `meeting_key` are considered, or all of `raw_dir` if it is None.
    A failed session writes nothing and is reported; the sessions after it are still loaded.
    """
    loaded = loaded_sessions(spark)
    count = failed = 0
    for marker in success_markers(raw_dir, meeting_key):
        session_dir = marker.parent
        session_key = int(session_dir.name.split("_")[0])
        completed_at = read_json(marker)["completed_at"]
        if loaded.get(session_key) == completed_at:
            print(f"skip  {session_dir} (already loaded)")
            continue
        try:
            rows = load_session(spark, session_dir, completed_at)
        except Exception as exc:  # noqa: BLE001 - report every failed session, then fail the step
            print(f"FAILED {session_dir}: {exc}", file=sys.stderr)
            failed += 1
            continue
        print(f"load  {session_dir}: {rows:,} rows")
        count += 1
    print(f"Loaded {count} sessions into bronze, {failed} failed")
    return failed
