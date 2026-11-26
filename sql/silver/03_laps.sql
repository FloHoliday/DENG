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
FROM bronze_laps
