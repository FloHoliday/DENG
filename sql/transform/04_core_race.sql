-- Core models per stint, pit stop, driver result, pass and undercut attempt.

-- Grain: (session_key, driver_number, stint_number).
CREATE MATERIALIZED VIEW core.fct_stint AS
WITH lap_stats AS (
    SELECT
        l.session_key,
        l.driver_number,
        l.stint_number,
        count(*) FILTER (WHERE l.is_clean_lap) AS n_clean_laps,
        avg(l.lap_duration_s) FILTER (WHERE l.is_clean_lap) AS avg_clean_lap_s,
        -- Degradation: seconds per lap of tyre age, fuel-corrected, clean laps only.
        regr_slope(l.fuel_corrected_lap_s, l.tyre_age) FILTER (WHERE l.is_clean_lap)
            AS deg_s_per_lap,
        -- Grip loss: change of slow-corner speed per lap of tyre age.
        regr_slope(t.p10_speed_kmh, l.tyre_age) FILTER (WHERE l.is_clean_lap)
            AS grip_loss_kmh_per_lap,
        avg(t.lift_coast_s) FILTER (WHERE l.is_clean_lap) AS avg_lift_coast_s,
        avg(l.track_temperature) AS avg_track_temperature
    FROM core.fct_lap AS l
    LEFT JOIN core.fct_lap_telemetry AS t USING (session_key, driver_number, lap_number)
    WHERE l.stint_number IS NOT NULL
    GROUP BY l.session_key, l.driver_number, l.stint_number
)
SELECT
    st.session_key,
    s.season,
    s.circuit_short_name,
    st.driver_number,
    d.name_acronym,
    d.team_name,
    st.stint_number,
    st.compound,
    st.is_slick,
    st.lap_start,
    st.lap_end,
    st.lap_end - st.lap_start + 1 AS stint_length,
    st.tyre_age_at_start,
    st.tyre_age_at_start + st.lap_end - st.lap_start AS tyre_age_at_end,
    coalesce(ls.n_clean_laps, 0) AS n_clean_laps,
    ls.avg_clean_lap_s,
    -- A slope from fewer than 5 laps is noise.
    CASE WHEN ls.n_clean_laps >= 5 THEN ls.deg_s_per_lap END AS deg_s_per_lap,
    CASE WHEN ls.n_clean_laps >= 5 THEN ls.grip_loss_kmh_per_lap END AS grip_loss_kmh_per_lap,
    ls.avg_lift_coast_s,
    ls.avg_track_temperature
FROM staging.stg_stints AS st
JOIN staging.stg_sessions AS s USING (session_key)
LEFT JOIN staging.stg_drivers AS d USING (session_key, driver_number)
LEFT JOIN lap_stats AS ls USING (session_key, driver_number, stint_number)
WHERE s.is_race;

CREATE UNIQUE INDEX ON core.fct_stint (session_key, driver_number, stint_number);

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
CREATE MATERIALIZED VIEW core.fct_pit_stop AS
WITH pit AS (
    SELECT
        p.*,
        EXISTS (
            SELECT 1
            FROM core.fct_neutralisation AS n
            WHERE n.session_key = p.session_key
              AND n.kind = 'RED'
              -- p.date is the pit exit; the car entered lane_duration_s earlier.
              AND p.date > n.start_date
              AND p.date - make_interval(secs => coalesce(p.lane_duration_s, 0)) < n.end_date
        ) AS is_red_flag
    FROM staging.stg_pit AS p
    JOIN staging.stg_sessions AS s USING (session_key)
    WHERE s.is_race AND p.lap_number IS NOT NULL
),
penalty_served AS (
    SELECT
        session_key,
        date,
        substring(message FROM 'CAR ([0-9]+)')::integer AS driver_number
    FROM staging.stg_race_control
    WHERE message ~ 'PENALTY SERVED - (DRIVE THROUGH|STOP AND GO|STOP/GO)'
),
penalty_stop AS (
    SELECT DISTINCT ON (ps.session_key, ps.driver_number, ps.date)
        p.session_key,
        p.driver_number,
        p.lap_number
    FROM penalty_served AS ps
    JOIN pit AS p
        ON p.session_key = ps.session_key
       AND p.driver_number = ps.driver_number
       AND p.date <= ps.date
       AND NOT p.is_red_flag
    ORDER BY ps.session_key, ps.driver_number, ps.date, p.date DESC
),
driver_pace AS (
    SELECT
        session_key,
        driver_number,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY lap_duration_s) AS median_clean_lap_s
    FROM core.fct_lap
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
JOIN staging.stg_sessions AS s USING (session_key)
LEFT JOIN core.fct_lap AS in_lap
    ON in_lap.session_key = p.session_key
   AND in_lap.driver_number = p.driver_number
   AND in_lap.lap_number = p.lap_number
LEFT JOIN core.fct_lap AS out_lap
    ON out_lap.session_key = p.session_key
   AND out_lap.driver_number = p.driver_number
   AND out_lap.lap_number = p.lap_number + 1
LEFT JOIN driver_pace AS dp
    ON dp.session_key = p.session_key AND dp.driver_number = p.driver_number;

CREATE UNIQUE INDEX ON core.fct_pit_stop (session_key, driver_number, lap_number);

-- Grain: (session_key, driver_number). Grid vs. finish and the strategy that was run.
CREATE MATERIALIZED VIEW core.fct_race_result AS
WITH strategies AS (
    SELECT
        session_key,
        driver_number,
        count(*) - 1 AS n_stops,
        -- Compound sequence, e.g. M-H or S-M-H (I = intermediate, W = wet, U = unknown).
        string_agg(left(compound, 1), '-' ORDER BY stint_number) AS strategy
    FROM core.fct_stint
    GROUP BY session_key, driver_number
)
SELECT
    r.session_key,
    s.season,
    s.circuit_short_name,
    r.driver_number,
    d.name_acronym,
    d.team_name,
    g.grid_position,
    r.finish_position,
    g.grid_position - r.finish_position AS positions_gained,
    r.points,
    r.dnf,
    r.dns,
    r.dsq,
    coalesce(st.n_stops, 0) AS n_stops,
    coalesce(st.strategy, 'UNKNOWN') AS strategy
FROM staging.stg_session_result AS r
JOIN staging.stg_sessions AS s USING (session_key)
LEFT JOIN staging.stg_drivers AS d USING (session_key, driver_number)
LEFT JOIN staging.stg_starting_grid AS g USING (session_key, driver_number)
LEFT JOIN strategies AS st USING (session_key, driver_number)
WHERE s.is_race;

CREATE UNIQUE INDEX ON core.fct_race_result (session_key, driver_number);

-- Grain: (session_key, lap_number, passing_driver, passed_driver).
-- An on-track pass: A was behind B at the end of the previous lap and ahead of B at the
-- end of this lap, under green flag, and neither car was on an in- or out-lap.
-- Not lap 1 (start positions) and only cars that both completed the lap.
CREATE MATERIALIZED VIEW core.fct_on_track_pass AS
SELECT
    a.session_key,
    a.lap_number,
    a.driver_number AS passing_driver,
    b.driver_number AS passed_driver
FROM core.fct_lap_position AS a
JOIN core.fct_lap_position AS a_prev
    ON a_prev.session_key = a.session_key
   AND a_prev.driver_number = a.driver_number
   AND a_prev.lap_number = a.lap_number - 1
JOIN core.fct_lap_position AS b
    ON b.session_key = a.session_key
   AND b.lap_number = a.lap_number
   AND b.driver_number <> a.driver_number
JOIN core.fct_lap_position AS b_prev
    ON b_prev.session_key = b.session_key
   AND b_prev.driver_number = b.driver_number
   AND b_prev.lap_number = b.lap_number - 1
WHERE a.lap_number > 1
  AND a_prev.position > b_prev.position
  AND a.position < b.position
  AND NOT (a.is_neutralised OR a.is_pit_in_lap OR a.is_pit_out_lap)
  AND NOT (b.is_pit_in_lap OR b.is_pit_out_lap);

CREATE UNIQUE INDEX ON core.fct_on_track_pass (session_key, lap_number, passing_driver, passed_driver);

-- Grain: (session_key, driver_number, lap_number) of the attacker's green-flag stop.
-- Undercut attempt: A is directly behind B at the end of the lap before A's stop, and B
-- stops 1 to 3 laps later. Success: A is ahead of B at the end of B's out-lap.
-- Both stops are real green-flag stops.
CREATE MATERIALIZED VIEW core.fct_undercut_attempt AS
SELECT
    a_stop.session_key,
    a_stop.season,
    a_stop.circuit_short_name,
    a_stop.driver_number,
    a_stop.lap_number,
    b_stop.driver_number AS defending_driver,
    b_stop.lap_number - a_stop.lap_number AS laps_later,
    a_after.position < b_after.position AS is_success
FROM core.fct_pit_stop AS a_stop
JOIN core.fct_lap_position AS a_before
    ON a_before.session_key = a_stop.session_key
   AND a_before.driver_number = a_stop.driver_number
   AND a_before.lap_number = a_stop.lap_number - 1
JOIN core.fct_lap_position AS b_before
    ON b_before.session_key = a_stop.session_key
   AND b_before.lap_number = a_before.lap_number
   AND b_before.position = a_before.position - 1
JOIN core.fct_pit_stop AS b_stop
    ON b_stop.session_key = a_stop.session_key
   AND b_stop.driver_number = b_before.driver_number
   AND b_stop.lap_number BETWEEN a_stop.lap_number + 1 AND a_stop.lap_number + 3
   AND b_stop.is_real_stop
   AND NOT b_stop.is_under_neutralisation
JOIN core.fct_lap_position AS a_after
    ON a_after.session_key = a_stop.session_key
   AND a_after.driver_number = a_stop.driver_number
   AND a_after.lap_number = b_stop.lap_number + 1
JOIN core.fct_lap_position AS b_after
    ON b_after.session_key = a_stop.session_key
   AND b_after.driver_number = b_stop.driver_number
   AND b_after.lap_number = b_stop.lap_number + 1
WHERE a_stop.is_real_stop AND NOT a_stop.is_under_neutralisation;

CREATE UNIQUE INDEX ON core.fct_undercut_attempt (session_key, driver_number, lap_number);
