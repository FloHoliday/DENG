-- Grain: (session_key, driver_number, lap_number). Running position at the end of each lap.
SELECT
    l.session_key,
    l.driver_number,
    l.lap_number,
    -- Order in which the cars crossed the line to complete this lap. Unique by
    -- construction (the position feed can give two cars the same position, because
    -- they finish the lap at different times); lapped cars cross later, so rank behind.
    row_number() OVER (
        PARTITION BY l.session_key, l.lap_number ORDER BY l.date_end, l.driver_number
    ) AS position,
    l.is_pit_in_lap,
    l.is_pit_out_lap,
    l.is_neutralised
FROM fct_lap AS l
WHERE l.date_end IS NOT NULL
