-- Staging: one plain view per raw table. Only renaming, typing and cleaning, no joins
-- and no copy of the data. Everything downstream reads from here, never from public.*.
CREATE SCHEMA IF NOT EXISTS staging;

-- OpenF1 also labels Sprints session_type 'Race', so session_name decides.
CREATE VIEW staging.stg_sessions AS
SELECT
    s.session_key,
    s.meeting_key,
    s.year AS season,
    s.circuit_short_name,
    m.meeting_name,
    s.country_name,
    s.session_name,
    s.session_name = 'Race' AS is_race,
    s.date_start,
    s.date_end
FROM public.sessions AS s
JOIN public.meetings AS m USING (meeting_key)
WHERE NOT coalesce(s.is_cancelled, false);

CREATE VIEW staging.stg_drivers AS
SELECT DISTINCT ON (session_key, driver_number)
    session_key,
    driver_number,
    name_acronym,
    full_name,
    team_name
FROM public.drivers
ORDER BY session_key, driver_number;

CREATE VIEW staging.stg_laps AS
SELECT
    session_key,
    driver_number,
    lap_number,
    date_start,
    lap_duration,
    duration_sector_1,
    duration_sector_2,
    duration_sector_3,
    st_speed AS speed_trap_kmh,
    coalesce(is_pit_out_lap, false) AS is_pit_out_lap
FROM public.laps;

-- One stint with a NULL compound exists; it becomes UNKNOWN instead of disappearing.
CREATE VIEW staging.stg_stints AS
SELECT
    session_key,
    driver_number,
    stint_number,
    coalesce(compound, 'UNKNOWN') AS compound,
    compound IN ('SOFT', 'MEDIUM', 'HARD') AS is_slick,
    lap_start,
    lap_end,
    coalesce(tyre_age_at_start, 0) AS tyre_age_at_start
FROM public.stints;

-- lap_number is the lap on which the car entered the pit lane (the in-lap).
-- pit_duration is deprecated and always equals lane_duration.
CREATE VIEW staging.stg_pit AS
SELECT
    session_key,
    driver_number,
    lap_number,
    date,
    lane_duration AS lane_duration_s,
    stop_duration AS stop_duration_s -- only from the 2024 US GP onwards
FROM public.pit;

-- event: the race-control messages that start or end a neutralisation.
-- lap_number is the leader's lap.
CREATE VIEW staging.stg_race_control AS
SELECT
    session_key,
    date,
    lap_number,
    category,
    flag,
    message,
    CASE
        WHEN message = 'SAFETY CAR DEPLOYED' THEN 'SC'
        WHEN message = 'VSC DEPLOYED' THEN 'VSC'
        WHEN message ~ '^RED FLAG' THEN 'RED'
        WHEN message = 'SAFETY CAR IN THIS LAP' THEN 'SC_END'
        WHEN message = 'VSC ENDING' THEN 'VSC_END'
        WHEN category = 'SessionStatus' AND message = 'SESSION STARTED' THEN 'START'
        WHEN flag = 'CHEQUERED' THEN 'FINISH'
    END AS event
FROM public.race_control;

CREATE VIEW staging.stg_weather AS
SELECT
    session_key,
    date,
    air_temperature,
    track_temperature,
    humidity,
    wind_speed,
    rainfall > 0 AS rainfall
FROM public.weather;

-- One row per position change (not per lap).
CREATE VIEW staging.stg_position AS
SELECT session_key, driver_number, date, position
FROM public.position;

-- gap_to_leader / interval are seconds or '+N LAP(S)': split into seconds and laps.
CREATE VIEW staging.stg_intervals AS
SELECT
    session_key,
    driver_number,
    date,
    CASE WHEN gap_to_leader ~ '^[0-9.]+$' THEN gap_to_leader::numeric END AS gap_to_leader_s,
    CASE WHEN "interval" ~ '^[0-9.]+$' THEN "interval"::numeric END AS interval_s,
    substring(gap_to_leader FROM '^\+([0-9]+) LAP')::integer AS laps_behind_leader
FROM public.intervals;

CREATE VIEW staging.stg_session_result AS
SELECT
    session_key,
    driver_number,
    position AS finish_position,
    number_of_laps,
    points,
    coalesce(dnf, false) AS dnf,
    coalesce(dns, false) AS dns,
    coalesce(dsq, false) AS dsq,
    CASE WHEN gap_to_leader ~ '^[0-9.]+$' THEN gap_to_leader::numeric END AS gap_to_leader_s,
    substring(gap_to_leader FROM '^\+([0-9]+) LAP')::integer AS laps_behind_leader
FROM public.session_result;

-- Keyed by the Race; qualifying_session_key is the session that set the grid.
CREATE VIEW staging.stg_starting_grid AS
SELECT
    race_session_key AS session_key,
    session_key AS qualifying_session_key,
    driver_number,
    position AS grid_position
FROM public.starting_grid;

-- throttle goes up to 104 (about 10 percent of samples): keep the raw value, add a 0-100 scale.
-- brake is 0, 100 or 104: on/off.
CREATE VIEW staging.stg_car_data AS
SELECT
    session_key,
    driver_number,
    date,
    speed AS speed_kmh,
    throttle,
    least(throttle, 100) AS throttle_pct,
    throttle >= 99 AS is_full_throttle,
    brake > 0 AS is_braking,
    n_gear,
    rpm
FROM public.car_data;
