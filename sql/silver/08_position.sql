-- One row per position change (not per lap).
SELECT session_key, driver_number, date, position
FROM bronze_position
