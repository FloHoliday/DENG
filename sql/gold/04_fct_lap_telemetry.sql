-- Grain: (session_key, driver_number, lap_number). Lap-level car telemetry from about
-- 0.8M car_data samples per race.
WITH laps AS (
    SELECT session_key, driver_number, lap_number, date_start, date_end
    FROM fct_lap
),
-- Samples only carry a timestamp. Lap starts are mixed into the same ordered stream,
-- and each sample takes the number of the last lap start before it.
marked AS (
    SELECT
        driver_number, date, speed_kmh, throttle_pct, is_full_throttle, is_braking,
        CAST(NULL AS INT) AS lap_start_number
    FROM silver_car_data
    UNION ALL
    SELECT driver_number, date_start, NULL, NULL, NULL, NULL, lap_number
    FROM laps
    WHERE date_start IS NOT NULL
),
tagged AS (
    SELECT
        *,
        max(lap_start_number) OVER (
            PARTITION BY driver_number
            ORDER BY date, lap_start_number NULLS LAST
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS lap_number
    FROM marked
),
samples AS (
    SELECT
        driver_number,
        lap_number,
        date,
        speed_kmh,
        throttle_pct,
        is_full_throttle,
        is_braking,
        lag(is_braking) OVER s AS was_braking,
        -- Time until the next sample, capped at 1 s to ignore data gaps.
        least((unix_micros(lead(date) OVER s) - unix_micros(date)) / 1e6, 1.0) AS dt_s
    FROM tagged
    WHERE lap_start_number IS NULL AND lap_number IS NOT NULL
    WINDOW s AS (PARTITION BY driver_number ORDER BY date)
)
SELECT
    l.session_key,
    s.driver_number,
    s.lap_number,
    count(*) AS n_samples,
    max(s.speed_kmh) AS top_speed_kmh,
    -- 10th percentile of speed: the slow corners, a proxy for mechanical grip.
    percentile_cont(0.1) WITHIN GROUP (ORDER BY s.speed_kmh) AS p10_speed_kmh,
    avg(s.speed_kmh) AS avg_speed_kmh,
    100.0 * avg(CAST(s.is_full_throttle AS INT)) AS full_throttle_pct,
    count(*) FILTER (WHERE s.is_braking AND NOT coalesce(s.was_braking, false))
        AS brake_events,
    -- Seconds at > 200 km/h with neither throttle nor brake: lift-and-coast (saving).
    coalesce(
        sum(s.dt_s) FILTER (WHERE s.throttle_pct <= 1 AND NOT s.is_braking AND s.speed_kmh > 200),
        0
    ) AS lift_coast_s
FROM samples AS s
JOIN laps AS l USING (driver_number, lap_number)
WHERE s.date < l.date_end
GROUP BY l.session_key, s.driver_number, s.lap_number
