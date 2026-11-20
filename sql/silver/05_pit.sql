-- lap_number is the lap on which the car entered the pit lane (the in-lap).
-- pit_duration is deprecated and always equals lane_duration.
SELECT
    session_key,
    driver_number,
    lap_number,
    date,
    lane_duration AS lane_duration_s,
    stop_duration AS stop_duration_s -- only from the 2024 US GP onwards
FROM bronze_pit
