-- Grain: (session_key, kind, start_date). One row per Safety Car, VSC or red-flag period.
-- A period lasts from its start message until the next start/end message of that race
-- (lap numbers are the leader's).
-- Race control can send a message twice: keep one per (race, event, time) ...
WITH distinct_events AS (
    SELECT session_key, date, lap_number, event
    FROM (
        SELECT
            rc.*,
            row_number() OVER (
                PARTITION BY rc.session_key, rc.event, rc.date
                ORDER BY rc.lap_number NULLS LAST
            ) AS n
        FROM silver_race_control AS rc
        JOIN silver_sessions AS s USING (session_key)
        WHERE s.is_race AND rc.event IS NOT NULL
    )
    WHERE n = 1
),
-- ... and drop a repeat of the previous event (e.g. SC deployed twice in a row), which
-- would otherwise start a second, overlapping period.
first_events AS (
    SELECT *
    FROM (
        SELECT
            *,
            lag(event) OVER (PARTITION BY session_key ORDER BY date, event) AS prev_event
        FROM distinct_events
    )
    WHERE prev_event IS DISTINCT FROM event
),
events AS (
    SELECT
        session_key,
        date,
        lap_number,
        event,
        lead(lap_number) OVER w AS next_lap,
        lead(date) OVER w AS next_date
    FROM first_events
    WINDOW w AS (PARTITION BY session_key ORDER BY date, event)
)
SELECT
    session_key,
    event AS kind,
    date AS start_date,
    next_date AS end_date,
    lap_number AS start_lap,
    coalesce(next_lap, lap_number) AS end_lap
FROM events
WHERE event IN ('SC', 'VSC', 'RED')
