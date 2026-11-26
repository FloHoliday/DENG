SELECT
    session_key,
    date,
    air_temperature,
    track_temperature,
    humidity,
    wind_speed,
    rainfall > 0 AS rainfall
FROM bronze_weather
