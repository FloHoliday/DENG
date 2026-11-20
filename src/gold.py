"""Gold step: build the facts and the mart of every race whose silver data changed.

The SQL in sql/gold/ is the v0.2 core + marts model, run per race. A race is checked as
a whole before any of its tables is published; readers keep the previous version until then.
"""

from pyspark.sql import DataFrame, SparkSession

import stage
from checks import Check, duplicates, sql_check

STAGE = "gold"
SILVER_TABLES = [
    "sessions", "drivers", "laps", "stints", "pit", "race_control", "weather",
    "position", "intervals", "session_result", "starting_grid", "car_data",
]  # fmt: skip
KEYS = {
    "fct_neutralisation": "session_key, kind, start_date",
    "fct_lap": "session_key, driver_number, lap_number",
    "fct_lap_position": "session_key, driver_number, lap_number",
    "fct_lap_telemetry": "session_key, driver_number, lap_number",
    "fct_stint": "session_key, driver_number, stint_number",
    "fct_pit_stop": "session_key, driver_number, lap_number",
    "fct_race_result": "session_key, driver_number",
    "fct_position_swap": "session_key, lap_number, gaining_driver, losing_driver",
    "fct_undercut_attempt": "session_key, driver_number, lap_number",
    "mart_race_outcome": "session_key, driver_number",
}
# Tables every race must have rows in (a race can have no neutralisation, swap or undercut).
NOT_EMPTY = ["fct_lap", "fct_lap_position", "fct_lap_telemetry", "fct_stint",
             "fct_race_result", "mart_race_outcome"]  # fmt: skip


def upstream(spark: SparkSession) -> DataFrame:
    """Every race built in silver, with the time of that build."""
    return stage.bookmarks(spark, "silver")


def register_inputs(spark: SparkSession, session_key: int) -> None:
    """The silver rows of one race as temp views silver_<table>."""
    for table in SILVER_TABLES:
        df = stage.read(spark, "silver", table).where(f"session_key = {session_key}")
        df.createOrReplaceTempView(f"silver_{table}")


def checks(spark: SparkSession) -> list[Check]:
    return [
        *(duplicates(spark, table, key) for table, key in KEYS.items()),
        *(
            Check(f"{table}: has rows", int(spark.table(table).isEmpty()))
            for table in NOT_EMPTY
        ),
        # Per race, OpenF1 misses the stint of up to 2 % of laps (v0.2: 263 of 97,018
        # laps in 87 races); a broken stint match would miss far more.
        *(
            sql_check(
                spark,
                f"fct_lap: every lap is assigned to a stint (max {pct} percent missing)",
                f"""SELECT int(count_if(stint_number IS NULL) > {pct / 100} * count(*)),
                           count_if(stint_number IS NULL) || ' of ' || count(*) || ' laps'
                    FROM fct_lap""",
                severity,
            )
            for pct, severity in ((5, "error"), (1, "warn"))
        ),
        sql_check(
            spark,
            "fct_lap: tyre age is never negative",
            """SELECT count(*), concat_ws(', ', collect_set(driver_number))
               FROM fct_lap WHERE tyre_age < 0""",
        ),
        sql_check(
            spark,
            "fct_stint: compound is a known value",
            """SELECT count(*), concat_ws(', ', collect_set(compound)) FROM fct_stint
               WHERE compound NOT IN ('SOFT', 'MEDIUM', 'HARD', 'INTERMEDIATE', 'WET', 'UNKNOWN')""",
        ),
        # Otherwise a served drive-through or stop-and-go would count as a real stop.
        sql_check(
            spark,
            "every served drive-through penalty is matched to a pit record",
            """SELECT count(*), concat_ws(', ', collect_set(rc.message))
               FROM silver_race_control AS rc
               WHERE rc.message RLIKE 'PENALTY SERVED - (DRIVE THROUGH|STOP AND GO|STOP/GO)'
                 AND NOT EXISTS (
                     SELECT 1 FROM fct_pit_stop AS p
                     WHERE p.session_key = rc.session_key
                       AND p.is_penalty
                       AND p.driver_number = CAST(
                           nullif(regexp_extract(rc.message, 'CAR ([0-9]+)', 1), '') AS INT)
                 )""",
        ),
        # Otherwise a position change is counted twice or missed.
        sql_check(
            spark,
            "mart_race_outcome: split adds up to positions gained",
            """SELECT count(*), concat_ws(', ', collect_set(driver_number))
               FROM mart_race_outcome
               WHERE gained_lap1 IS NOT NULL
                 AND gained_lap1 + gained_on_track + gained_in_pits + gained_other
                     <> positions_gained""",
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
        "",
        checks,
        full_refresh,
        meeting_key,
    )
