-- Keyed by the Race; qualifying_session_key is the session that set the grid.
SELECT
    race_session_key AS session_key,
    session_key AS qualifying_session_key,
    driver_number,
    position AS grid_position
FROM bronze_starting_grid
