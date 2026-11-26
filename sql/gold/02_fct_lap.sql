-- Grain: one row per race lap of a driver (session_key, driver_number, lap_number).
WITH race_laps AS (
    SELECT
        l.*,
        s.season,
        s.meeting_key,
        s.circuit_short_name,
        max(l.lap_number) OVER (PARTITION BY l.session_key) AS total_laps,
        -- End of the lap: start of the driver's next lap, or start + duration on the last
        -- lap and when the next lap is missing in the source (a few laps are).
        coalesce(
            CASE
                WHEN lead(l.lap_number) OVER w = l.lap_number + 1 THEN lead(l.date_start) OVER w
            END,
            l.date_start + make_dt_interval(0, 0, 0, CAST(l.lap_duration AS DECIMAL(18, 6)))
        ) AS date_end
    FROM silver_laps AS l
    JOIN silver_sessions AS s USING (session_key)
    WHERE s.is_race
    WINDOW w AS (PARTITION BY l.session_key, l.driver_number ORDER BY l.lap_number)
),
pit_laps AS (
    SELECT DISTINCT session_key, driver_number, lap_number FROM silver_pit
),
neutralised_laps AS (
    SELECT DISTINCT l.session_key, l.lap_number
    FROM race_laps AS l
    JOIN fct_neutralisation AS n
        ON n.session_key = l.session_key AND l.lap_number BETWEEN n.start_lap AND n.end_lap
),
-- The stint the lap belongs to (the later one if two overlap).
lap_stint AS (
    SELECT *
    FROM (
        SELECT
            l.session_key,
            l.driver_number,
            l.lap_number,
            st.stint_number,
            st.compound,
            st.is_slick,
            st.tyre_age_at_start + l.lap_number - st.lap_start AS tyre_age,
            row_number() OVER (
                PARTITION BY l.session_key, l.driver_number, l.lap_number
                ORDER BY st.stint_number DESC
            ) AS n
        FROM race_laps AS l
        JOIN silver_stints AS st
            ON st.session_key = l.session_key
           AND st.driver_number = l.driver_number
           AND l.lap_number BETWEEN st.lap_start AND st.lap_end
    )
    WHERE n = 1
),
-- Weather is sampled about once a minute: take the last sample before the lap.
lap_weather AS (
    SELECT *
    FROM (
        SELECT
            l.session_key,
            l.driver_number,
            l.lap_number,
            w.track_temperature,
            w.air_temperature,
            w.rainfall,
            row_number() OVER (
                PARTITION BY l.session_key, l.driver_number, l.lap_number ORDER BY w.date DESC
            ) AS n
        FROM race_laps AS l
        JOIN silver_weather AS w
            ON w.session_key = l.session_key AND w.date <= l.date_start
    )
    WHERE n = 1
),
enriched AS (
    SELECT
        rl.*,
        d.name_acronym,
        d.team_name,
        st.stint_number,
        st.compound,
        st.is_slick,
        st.tyre_age,
        p.lap_number IS NOT NULL AS is_pit_in_lap,
        nl.lap_number IS NOT NULL AS is_neutralised,
        w.track_temperature,
        w.air_temperature,
        coalesce(w.rainfall, false) AS rainfall
    FROM race_laps AS rl
    LEFT JOIN silver_drivers AS d USING (session_key, driver_number)
    LEFT JOIN lap_stint AS st USING (session_key, driver_number, lap_number)
    LEFT JOIN pit_laps AS p USING (session_key, driver_number, lap_number)
    LEFT JOIN neutralised_laps AS nl USING (session_key, lap_number)
    LEFT JOIN lap_weather AS w USING (session_key, driver_number, lap_number)
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
LEFT JOIN driver_pace AS dp USING (session_key, driver_number)
