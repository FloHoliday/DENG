-- Data checks, run by the validate step (scripts/validate.py) after every transform.
-- One row per check: (check, failures, detail). failures = 0 means PASS.
-- Can also be run on its own in pgAdmin to see the same result.
WITH loaded_races AS (
    SELECT ls.session_key
    FROM raw.loaded_sessions AS ls
    JOIN staging.stg_sessions AS s USING (session_key)
    WHERE s.is_race
),
mart_rows AS (
    SELECT 'mart_strategy_per_circuit' AS mart, count(*) AS n FROM marts.mart_strategy_per_circuit
    UNION ALL SELECT 'mart_safety_car_risk', count(*) FROM marts.mart_safety_car_risk
    UNION ALL SELECT 'mart_pit_loss', count(*) FROM marts.mart_pit_loss
    UNION ALL SELECT 'mart_overtaking_difficulty', count(*) FROM marts.mart_overtaking_difficulty
    UNION ALL SELECT 'mart_weather_effect', count(*) FROM marts.mart_weather_effect
    UNION ALL SELECT 'mart_tyre_degradation', count(*) FROM marts.mart_tyre_degradation
    UNION ALL SELECT 'mart_pit_window', count(*) FROM marts.mart_pit_window
    UNION ALL SELECT 'mart_team_tyre_management', count(*) FROM marts.mart_team_tyre_management
    UNION ALL SELECT 'mart_undercut', count(*) FROM marts.mart_undercut
    UNION ALL SELECT 'mart_grip_loss', count(*) FROM marts.mart_grip_loss
    UNION ALL SELECT 'mart_circuit_character', count(*) FROM marts.mart_circuit_character
)

SELECT 'raw laps: one row per (session, driver, lap)' AS check, count(*) AS failures,
       string_agg(DISTINCT session_key::text, ', ') AS detail
FROM (
    SELECT session_key FROM raw.laps
    GROUP BY session_key, driver_number, lap_number HAVING count(*) > 1
) AS d

UNION ALL
SELECT 'raw stints: one row per (session, driver, stint)', count(*),
       string_agg(DISTINCT session_key::text, ', ')
FROM (
    SELECT session_key FROM raw.stints
    GROUP BY session_key, driver_number, stint_number HAVING count(*) > 1
) AS d

UNION ALL
SELECT 'raw pit: one row per (session, driver, lap)', count(*),
       string_agg(DISTINCT session_key::text, ', ')
FROM (
    SELECT session_key FROM raw.pit
    GROUP BY session_key, driver_number, lap_number HAVING count(*) > 1
) AS d

UNION ALL
SELECT 'every loaded race has a result and a starting grid', count(*),
       string_agg(r.session_key::text, ', ')
FROM loaded_races AS r
WHERE NOT EXISTS (SELECT 1 FROM raw.session_result AS x WHERE x.session_key = r.session_key)
   OR NOT EXISTS (SELECT 1 FROM raw.starting_grid AS x WHERE x.race_session_key = r.session_key)

UNION ALL
SELECT 'every loaded race is in core.fct_lap', count(*), string_agg(r.session_key::text, ', ')
FROM loaded_races AS r
WHERE NOT EXISTS (SELECT 1 FROM core.fct_lap AS l WHERE l.session_key = r.session_key)

UNION ALL
SELECT 'telemetry is up to date for every loaded race', count(*),
       string_agg(r.session_key::text, ', ')
FROM loaded_races AS r
JOIN raw.loaded_sessions AS ls USING (session_key)
LEFT JOIN core.telemetry_sessions AS t USING (session_key)
WHERE t.source_loaded_at IS DISTINCT FROM ls.loaded_at
   OR NOT EXISTS (SELECT 1 FROM core.fct_lap_telemetry AS x WHERE x.session_key = r.session_key)

UNION ALL
SELECT 'stint compound is a known value', count(*), string_agg(DISTINCT compound, ', ')
FROM core.fct_stint
WHERE compound NOT IN ('SOFT', 'MEDIUM', 'HARD', 'INTERMEDIATE', 'WET', 'UNKNOWN')

UNION ALL
SELECT 'tyre age is never negative', count(*), string_agg(DISTINCT session_key::text, ', ')
FROM core.fct_lap
WHERE tyre_age < 0

UNION ALL
SELECT 'every lap is assigned to a stint (max 1 percent missing)',
       (count(*) FILTER (WHERE stint_number IS NULL) > 0.01 * count(*))::integer,
       count(*) FILTER (WHERE stint_number IS NULL) || ' of ' || count(*) || ' laps'
FROM core.fct_lap

UNION ALL
-- Every served drive-through or stop-and-go penalty must be matched to a pit record,
-- otherwise it would be counted as a real stop.
SELECT 'every served drive-through penalty is matched to a pit record', count(*),
       string_agg(DISTINCT rc.session_key::text, ', ')
FROM staging.stg_race_control AS rc
JOIN staging.stg_sessions AS s USING (session_key)
WHERE s.is_race
  AND rc.message ~ 'PENALTY SERVED - (DRIVE THROUGH|STOP AND GO|STOP/GO)'
  AND NOT EXISTS (
      SELECT 1 FROM core.fct_pit_stop AS p
      WHERE p.session_key = rc.session_key
        AND p.is_penalty
        AND p.driver_number = substring(rc.message FROM 'CAR ([0-9]+)')::integer
  )

UNION ALL
SELECT 'every mart has rows', count(*) FILTER (WHERE n = 0),
       string_agg(mart, ', ') FILTER (WHERE n = 0)
FROM mart_rows;
