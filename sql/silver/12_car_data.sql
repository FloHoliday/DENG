-- throttle goes up to 104 (about 10 percent of samples): keep the raw value, add a 0-100 scale.
-- brake is 0, 100 or 104: on/off.
-- n_gear has glitches up to 200+ (about 1 in 10,000 samples in some races): set to NULL.
SELECT
    session_key,
    driver_number,
    date,
    speed AS speed_kmh,
    throttle,
    least(throttle, 100) AS throttle_pct,
    throttle >= 99 AS is_full_throttle,
    brake > 0 AS is_braking,
    CASE WHEN n_gear BETWEEN 0 AND 8 THEN n_gear END AS n_gear,
    rpm
FROM bronze_car_data
