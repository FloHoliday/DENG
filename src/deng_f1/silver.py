"""Silver step: clean and conform the bronze tables of every new or reloaded race.

The SQL in sql/silver/ only renames, types and cleans one bronze table each, no joins
(except sessions + meetings). Gold reads only from silver, never from bronze.
"""

from pyspark.sql import DataFrame, SparkSession

from . import bronze, stage
from .checks import Check, sql_check

STAGE = "silver"
# A timestamp this far outside the race's start and end is flagged; car data starts
# about an hour before the race (formation lap, cars leaving the garage).
WINDOW_HOURS = 2


def upstream(spark: SparkSession) -> DataFrame:
    """Every loaded, not cancelled Race with the time it was loaded into bronze."""
    sessions = spark.read.format("delta").load(bronze.table_path("sessions"))
    races = sessions.where(
        "session_name = 'Race' AND NOT coalesce(is_cancelled, false)"
    )
    return stage.bookmarks(spark, "bronze").join(
        races.select("session_key"), "session_key"
    )


def register_inputs(spark: SparkSession, session_key: int) -> None:
    """The bronze rows of one race as temp views bronze_<table>."""
    for table in bronze.SESSION_TABLES:
        key = bronze.KEY_COLUMNS.get(table, "session_key")
        df = spark.read.format("delta").load(bronze.table_path(table))
        df.where(f"{key} = {session_key}").createOrReplaceTempView(f"bronze_{table}")
    sessions = spark.read.format("delta").load(bronze.table_path("sessions"))
    race = sessions.where(f"session_key = {session_key}")
    race.createOrReplaceTempView("bronze_sessions")
    meetings = spark.read.format("delta").load(bronze.table_path("meetings"))
    meetings.join(race.select("meeting_key"), "meeting_key").createOrReplaceTempView(
        "bronze_meetings"
    )


def outside_window(table: str, column: str = "date") -> str:
    return f"""
        SELECT '{table}' AS t, count(*) AS n FROM bronze_{table} AS x, silver_sessions AS s
        WHERE x.{column} < s.date_start - INTERVAL {WINDOW_HOURS} HOURS
           OR x.{column} > s.date_end + INTERVAL {WINDOW_HOURS} HOURS
    """


def checks(spark: SparkSession) -> list[Check]:
    tables = ["car_data", "position", "intervals", "weather", "pit", "race_control"]
    windows = " UNION ALL ".join(
        [outside_window(t) for t in tables] + [outside_window("laps", "date_start")]
    )
    return [
        sql_check(
            spark,
            "car_data: speed 0-400, throttle_pct 0-100, n_gear 0-8",
            """SELECT count(*), concat_ws(', ', slice(collect_set(driver_number), 1, 5))
               FROM silver_car_data
               WHERE speed_kmh NOT BETWEEN 0 AND 400
                  OR throttle_pct NOT BETWEEN 0 AND 100
                  OR n_gear NOT BETWEEN 0 AND 8""",
        ),
        sql_check(
            spark,
            "car_data: n_gear glitches (outside 0-8) set to NULL",
            """SELECT count(*), concat_ws(', ', slice(collect_set(n_gear), 1, 5))
               FROM bronze_car_data WHERE n_gear NOT BETWEEN 0 AND 8""",
            "warn",
        ),
        sql_check(
            spark,
            "stints: tyre age at start is not negative",
            """SELECT count(*), concat_ws(', ', collect_set(driver_number))
               FROM silver_stints WHERE tyre_age_at_start < 0""",
        ),
        sql_check(
            spark,
            "gap_to_leader / interval: seconds or '+N LAP(S)'",
            r"""SELECT count(*), concat_ws(', ', slice(collect_set(v), 1, 5))
                FROM (
                    SELECT gap_to_leader AS v FROM bronze_intervals
                    UNION ALL SELECT `interval` FROM bronze_intervals
                    UNION ALL SELECT gap_to_leader FROM bronze_session_result
                )
                WHERE v IS NOT NULL
                  AND NOT v RLIKE '^[0-9.]+$' AND NOT v RLIKE '^[+][0-9]+ LAPS?$'""",
        ),
        sql_check(
            spark,
            f"timestamps within {WINDOW_HOURS} h of the race",
            f"""SELECT sum(n), concat_ws(', ', collect_list(CASE WHEN n > 0 THEN t || ': ' || n END))
                FROM ({windows})""",
            "warn",
        ),
    ]


def run(
    spark: SparkSession, full_refresh: bool = False, meeting_key: int | None = None
) -> int:
    return stage.run(
        spark,
        STAGE,
        upstream(spark),
        register_inputs,
        "silver_",
        checks,
        full_refresh,
        meeting_key,
    )
