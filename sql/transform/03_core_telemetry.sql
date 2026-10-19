-- Lap-level car telemetry. car_data is the only large table (about 0.8M samples per race),
-- so this is an incremental TABLE instead of a materialized view: only sessions that were
-- (re)loaded since their last aggregation are recomputed, each one replaced as a whole.
-- `scripts/transform.py --full-refresh` rebuilds it from scratch (needed after changing it).
CREATE TABLE IF NOT EXISTS core.fct_lap_telemetry (
    session_key INTEGER NOT NULL,
    driver_number INTEGER NOT NULL,
    lap_number INTEGER NOT NULL,
    n_samples INTEGER NOT NULL,
    top_speed_kmh INTEGER,
    -- 10th percentile of speed: the slow corners, a proxy for mechanical grip.
    p10_speed_kmh DOUBLE PRECISION,
    avg_speed_kmh DOUBLE PRECISION,
    full_throttle_pct DOUBLE PRECISION,
    brake_events INTEGER NOT NULL,
    -- Seconds at > 200 km/h with neither throttle nor brake: lift-and-coast (saving).
    lift_coast_s DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (session_key, driver_number, lap_number)
);

-- Which load of each session the telemetry was computed from.
CREATE TABLE IF NOT EXISTS core.telemetry_sessions (
    session_key INTEGER PRIMARY KEY,
    source_loaded_at TIMESTAMPTZ NOT NULL,
    aggregated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
DECLARE
    todo RECORD;
BEGIN
    FOR todo IN
        SELECT ls.session_key, ls.loaded_at
        FROM raw.loaded_sessions AS ls
        JOIN staging.stg_sessions AS s USING (session_key)
        LEFT JOIN core.telemetry_sessions AS t USING (session_key)
        WHERE s.is_race AND t.source_loaded_at IS DISTINCT FROM ls.loaded_at
        ORDER BY ls.session_key
    LOOP
        DELETE FROM core.fct_lap_telemetry WHERE session_key = todo.session_key;

        INSERT INTO core.fct_lap_telemetry
        WITH laps AS (
            SELECT session_key, driver_number, lap_number, date_start, date_end
            FROM core.fct_lap
            WHERE session_key = todo.session_key
        ),
        -- Samples only carry a timestamp. Lap starts are mixed into the same ordered
        -- stream, and each sample takes the number of the last lap start before it.
        marked AS (
            SELECT driver_number, date, speed_kmh, throttle_pct, is_full_throttle,
                   is_braking, NULL::integer AS lap_start_number
            FROM staging.stg_car_data
            WHERE session_key = todo.session_key
            UNION ALL
            SELECT driver_number, date_start, NULL, NULL, NULL, NULL, lap_number
            FROM laps
        ),
        tagged AS (
            SELECT
                *,
                max(lap_start_number) OVER (
                    PARTITION BY driver_number
                    ORDER BY date, lap_start_number NULLS LAST
                    ROWS UNBOUNDED PRECEDING
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
                least(extract(epoch FROM lead(date) OVER s - date), 1.0) AS dt_s
            FROM tagged
            WHERE lap_start_number IS NULL AND lap_number IS NOT NULL
            WINDOW s AS (PARTITION BY driver_number ORDER BY date)
        )
        SELECT
            todo.session_key,
            s.driver_number,
            s.lap_number,
            count(*),
            max(s.speed_kmh),
            percentile_cont(0.1) WITHIN GROUP (ORDER BY s.speed_kmh),
            avg(s.speed_kmh),
            100.0 * avg(s.is_full_throttle::integer),
            count(*) FILTER (WHERE s.is_braking AND NOT coalesce(s.was_braking, false)),
            coalesce(sum(s.dt_s) FILTER (
                WHERE s.throttle_pct <= 1 AND NOT s.is_braking AND s.speed_kmh > 200
            ), 0)
        FROM samples AS s
        JOIN laps AS l USING (driver_number, lap_number)
        WHERE s.date < l.date_end
        GROUP BY s.driver_number, s.lap_number;

        INSERT INTO core.telemetry_sessions (session_key, source_loaded_at)
        VALUES (todo.session_key, todo.loaded_at)
        ON CONFLICT (session_key) DO UPDATE
        SET source_loaded_at = EXCLUDED.source_loaded_at, aggregated_at = now();
    END LOOP;
END
$$;
