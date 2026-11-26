-- One stint with a NULL compound exists; it becomes UNKNOWN instead of disappearing.
SELECT
    session_key,
    driver_number,
    stint_number,
    coalesce(compound, 'UNKNOWN') AS compound,
    coalesce(compound IN ('SOFT', 'MEDIUM', 'HARD'), false) AS is_slick,
    lap_start,
    lap_end,
    coalesce(tyre_age_at_start, 0) AS tyre_age_at_start
FROM bronze_stints
