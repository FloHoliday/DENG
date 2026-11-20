-- Grain: (session_key, driver_number, stint_number).
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
    FROM fct_lap AS l
    LEFT JOIN fct_lap_telemetry AS t USING (session_key, driver_number, lap_number)
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
FROM silver_stints AS st
JOIN silver_sessions AS s USING (session_key)
LEFT JOIN silver_drivers AS d USING (session_key, driver_number)
LEFT JOIN lap_stats AS ls USING (session_key, driver_number, stint_number)
WHERE s.is_race
