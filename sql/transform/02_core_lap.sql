-- Core lap models: materialized views, rebuilt on every run. The unique index on the
-- grain makes the build fail instead of silently duplicating rows.
CREATE SCHEMA IF NOT EXISTS core;

-- One row per Safety Car, VSC or red-flag period. A period lasts from its start
-- message until the next start/end message of that race (lap numbers are the leader's).
CREATE MATERIALIZED VIEW core.fct_neutralisation AS
WITH events AS (
    SELECT
        rc.session_key,
        rc.date,
        rc.lap_number,
        rc.event,
        lead(rc.lap_number) OVER w AS next_lap,
        lead(rc.date) OVER w AS next_date
    FROM staging.stg_race_control AS rc
    JOIN staging.stg_sessions AS s USING (session_key)
    WHERE s.is_race AND rc.event IS NOT NULL
    WINDOW w AS (PARTITION BY rc.session_key ORDER BY rc.date, rc.event)
)
SELECT
    session_key,
    event AS kind,
    date AS start_date,
    next_date AS end_date,
    lap_number AS start_lap,
    coalesce(next_lap, lap_number) AS end_lap
FROM events
WHERE event IN ('SC', 'VSC', 'RED');

CREATE UNIQUE INDEX ON core.fct_neutralisation (session_key, kind, start_date);

-- Grain: one row per race lap of a driver (session_key, driver_number, lap_number).
CREATE MATERIALIZED VIEW core.fct_lap AS
WITH race_laps AS (
    SELECT
        l.*,
        s.season,
        s.meeting_key,
        s.circuit_short_name,
        max(l.lap_number) OVER (PARTITION BY l.session_key) AS total_laps,
        -- End of the lap: start of the driver's next lap, or start + duration on the last.
        coalesce(
            lead(l.date_start) OVER (
                PARTITION BY l.session_key, l.driver_number ORDER BY l.lap_number
            ),
            l.date_start + make_interval(secs => l.lap_duration)
        ) AS date_end
    FROM staging.stg_laps AS l
    JOIN staging.stg_sessions AS s USING (session_key)
    WHERE s.is_race
),
enriched AS (
    SELECT
        rl.*,
        d.name_acronym,
        d.team_name,
        st.stint_number,
        st.compound,
        st.is_slick,
        st.tyre_age_at_start + rl.lap_number - st.lap_start AS tyre_age,
        EXISTS (
            SELECT 1 FROM staging.stg_pit AS p
            WHERE p.session_key = rl.session_key
              AND p.driver_number = rl.driver_number
              AND p.lap_number = rl.lap_number
        ) AS is_pit_in_lap,
        EXISTS (
            SELECT 1 FROM core.fct_neutralisation AS n
            WHERE n.session_key = rl.session_key
              AND rl.lap_number BETWEEN n.start_lap AND n.end_lap
        ) AS is_neutralised,
        w.track_temperature,
        w.air_temperature,
        coalesce(w.rainfall, false) AS rainfall
    FROM race_laps AS rl
    LEFT JOIN staging.stg_drivers AS d USING (session_key, driver_number)
    LEFT JOIN LATERAL (
        SELECT * FROM staging.stg_stints AS st
        WHERE st.session_key = rl.session_key
          AND st.driver_number = rl.driver_number
          AND rl.lap_number BETWEEN st.lap_start AND st.lap_end
        ORDER BY st.stint_number DESC
        LIMIT 1
    ) AS st ON true
    -- Weather is sampled about once a minute: take the last sample before the lap.
    LEFT JOIN LATERAL (
        SELECT * FROM staging.stg_weather AS w
        WHERE w.session_key = rl.session_key AND w.date <= rl.date_start
        ORDER BY w.date DESC
        LIMIT 1
    ) AS w ON true
),
-- Fuel correction: every kg of fuel costs about 0.03 s per lap, a race starts with about
-- 100 kg and burns the same amount every lap (rule of thumb, not measured per car).
-- Subtracting the effect of the remaining fuel makes early and late laps comparable.
-- Sources: Michelin Simulation, "Showing our sensitive side" (2018), 0.03 s per kg
--   https://simulation.michelin.com/canopy/technical-articles/showing-our-sensitive-side
-- TracingInsights, same formula with 100 kg and linear burn
--   https://github.com/TracingInsights/2026
corrected AS (
    SELECT
        *,
        lap_duration - 0.03 * 100.0 * (total_laps - lap_number) / total_laps
            AS fuel_corrected_lap_s,
        lap_number > 1
            AND NOT is_pit_in_lap
            AND NOT is_pit_out_lap
            AND NOT is_neutralised
            AND NOT rainfall
            AND lap_duration IS NOT NULL AS is_green_lap
    FROM enriched
),
driver_pace AS (
    SELECT
        session_key,
        driver_number,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY lap_duration) AS median_green_lap_s
    FROM corrected
    WHERE is_green_lap
    GROUP BY session_key, driver_number
)
SELECT
    c.session_key,
    c.season,
    c.meeting_key,
    c.circuit_short_name,
    c.driver_number,
    c.name_acronym,
    c.team_name,
    c.lap_number,
    c.total_laps,
    c.date_start,
    c.date_end,
    c.lap_duration AS lap_duration_s,
    c.duration_sector_1,
    c.duration_sector_2,
    c.duration_sector_3,
    c.speed_trap_kmh,
    c.stint_number,
    c.compound,
    c.is_slick,
    c.tyre_age,
    c.is_pit_in_lap,
    c.is_pit_out_lap,
    c.is_neutralised,
    c.track_temperature,
    c.air_temperature,
    c.rainfall,
    c.fuel_corrected_lap_s,
    -- Clean lap: representative race pace. Green flag, no pit, no rain, not lap 1, and
    -- not slower than 107 percent of the driver's median green lap (traffic, mistakes).
    c.is_green_lap AND c.lap_duration < 1.07 * dp.median_green_lap_s AS is_clean_lap
FROM corrected AS c
LEFT JOIN driver_pace AS dp USING (session_key, driver_number);

CREATE UNIQUE INDEX ON core.fct_lap (session_key, driver_number, lap_number);
CREATE INDEX ON core.fct_lap (circuit_short_name, season);

-- Grain: (session_key, driver_number, lap_number). Running position at the end of each
-- lap: the last position change before the lap ended.
CREATE MATERIALIZED VIEW core.fct_lap_position AS
SELECT
    l.session_key,
    l.driver_number,
    l.lap_number,
    p.position,
    l.is_pit_in_lap,
    l.is_pit_out_lap,
    l.is_neutralised
FROM core.fct_lap AS l
JOIN LATERAL (
    SELECT p.position FROM staging.stg_position AS p
    WHERE p.session_key = l.session_key
      AND p.driver_number = l.driver_number
      AND p.date <= l.date_end
    ORDER BY p.date DESC
    LIMIT 1
) AS p ON true
WHERE l.date_end IS NOT NULL;

CREATE UNIQUE INDEX ON core.fct_lap_position (session_key, driver_number, lap_number);
CREATE INDEX ON core.fct_lap_position (session_key, lap_number);
