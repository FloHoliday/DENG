-- Grain: (session_key, driver_number, lap_number) of the in-lap. One row per pit record.
-- Not every pit record is a real stop:
--   is_red_flag: the car was in the pit lane during a red flag (all cars wait there, so
--     the pit lane time is 20 to 40 minutes), or left it at the restart.
--   is_penalty: a drive-through or stop-and-go penalty, matched by race control's
--     "PENALTY SERVED" message (the last pit record of that car before the message).
-- stop_number, pit loss and undercuts only use real stops (is_real_stop).
-- The stint data is not used for this: OpenF1 also starts a new stint after a penalty
-- or a red flag, and misses some real stops.
-- pit_loss_s: in-lap + out-lap compared with two of the driver's median green laps.
WITH race_pit AS (
    SELECT p.*
    FROM silver_pit AS p
    JOIN silver_sessions AS s USING (session_key)
    WHERE s.is_race AND p.lap_number IS NOT NULL
),
red_flag_pit AS (
    SELECT DISTINCT p.session_key, p.driver_number, p.lap_number
    FROM race_pit AS p
    JOIN fct_neutralisation AS n
        ON n.session_key = p.session_key
       AND n.kind = 'RED'
       -- p.date is the pit exit; the car entered lane_duration_s earlier.
       AND p.date > n.start_date
       AND p.date - make_dt_interval(0, 0, 0, CAST(coalesce(p.lane_duration_s, 0) AS DECIMAL(18, 6)))
           < n.end_date
),
pit AS (
    SELECT p.*, r.lap_number IS NOT NULL AS is_red_flag
    FROM race_pit AS p
    LEFT JOIN red_flag_pit AS r USING (session_key, driver_number, lap_number)
),
penalty_served AS (
    SELECT
        session_key,
        date,
        CAST(nullif(regexp_extract(message, 'CAR ([0-9]+)', 1), '') AS INT) AS driver_number
    FROM silver_race_control
    WHERE message RLIKE 'PENALTY SERVED - (DRIVE THROUGH|STOP AND GO|STOP/GO)'
),
penalty_stop AS (
    SELECT session_key, driver_number, lap_number
    FROM (
        SELECT
            p.session_key,
            p.driver_number,
            p.lap_number,
            row_number() OVER (
                PARTITION BY ps.session_key, ps.driver_number, ps.date ORDER BY p.date DESC
            ) AS n
        FROM penalty_served AS ps
        JOIN pit AS p
            ON p.session_key = ps.session_key
           AND p.driver_number = ps.driver_number
           AND p.date <= ps.date
           AND NOT p.is_red_flag
    )
    WHERE n = 1
),
driver_pace AS (
    SELECT
        session_key,
        driver_number,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY lap_duration_s) AS median_clean_lap_s
    FROM fct_lap
    WHERE is_clean_lap
    GROUP BY session_key, driver_number
),
classified AS (
    SELECT
        p.*,
        ps.lap_number IS NOT NULL AS is_penalty,
        NOT p.is_red_flag AND ps.lap_number IS NULL AS is_real_stop
    FROM pit AS p
    LEFT JOIN penalty_stop AS ps USING (session_key, driver_number, lap_number)
)
SELECT
    p.session_key,
    s.season,
    s.circuit_short_name,
    p.driver_number,
    in_lap.team_name,
    p.lap_number,
    p.lane_duration_s,
    p.stop_duration_s,
    in_lap.is_neutralised OR coalesce(out_lap.is_neutralised, false) AS is_under_neutralisation,
    p.is_red_flag,
    p.is_penalty,
    p.is_real_stop,
    in_lap.compound AS compound_before,
    out_lap.compound AS compound_after,
    in_lap.tyre_age AS tyre_age_at_stop,
    in_lap.lap_duration_s + out_lap.lap_duration_s - 2 * dp.median_clean_lap_s AS pit_loss_s,
    CASE WHEN p.is_real_stop THEN
        row_number() OVER (
            PARTITION BY p.session_key, p.driver_number, p.is_real_stop ORDER BY p.lap_number
        )
    END AS stop_number
FROM classified AS p
JOIN silver_sessions AS s USING (session_key)
LEFT JOIN fct_lap AS in_lap
    ON in_lap.session_key = p.session_key
   AND in_lap.driver_number = p.driver_number
   AND in_lap.lap_number = p.lap_number
LEFT JOIN fct_lap AS out_lap
    ON out_lap.session_key = p.session_key
   AND out_lap.driver_number = p.driver_number
   AND out_lap.lap_number = p.lap_number + 1
LEFT JOIN driver_pace AS dp
    ON dp.session_key = p.session_key AND dp.driver_number = p.driver_number
