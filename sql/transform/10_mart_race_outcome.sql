-- Mart: how do tyre and pit strategy and on-track position changes decide race outcomes?
-- Grain: (session_key, driver_number). One row per driver per race.
--
-- positions_gained (grid - finish) is split into four parts that add up exactly
-- (checked in sql/verify.sql); positive = positions won:
--   gained_lap1      start and first lap: grid - position at the end of lap 1
--   gained_on_track  overtakes under green flag (made minus suffered), laps 2 to the end
--   gained_in_pits   swaps where one of the two cars was on a pit in- or out-lap: positions
--                    lost by the own stops and won when cars ahead stop
--   gained_other     swaps under Safety Car/VSC without a pit stop, cars ahead retiring,
--                    laps missing in the source data, and the difference between the
--                    last lap and the official result (time penalties)
-- The split is only filled for classified finishers with a grid position.
-- The strategy columns describe what the driver did, as features for analysis or ML.
CREATE SCHEMA IF NOT EXISTS marts;

CREATE MATERIALIZED VIEW marts.mart_race_outcome AS
WITH last_lap AS (
    SELECT DISTINCT ON (session_key, driver_number)
        session_key,
        driver_number,
        lap_number AS last_lap,
        position AS last_lap_position
    FROM core.fct_lap_position
    ORDER BY session_key, driver_number, lap_number DESC
),
swaps AS (
    SELECT session_key, driver_number, cause, sum(delta) AS net
    FROM (
        SELECT session_key, gaining_driver AS driver_number, cause, 1 AS delta
        FROM core.fct_position_swap
        UNION ALL
        SELECT session_key, losing_driver, cause, -1
        FROM core.fct_position_swap
    ) AS s
    GROUP BY session_key, driver_number, cause
),
-- Cars that were ahead at the end of the previous lap and did not complete this lap.
retired_ahead AS (
    SELECT me.session_key, me.driver_number, count(*) AS n
    FROM core.fct_lap_position AS me
    JOIN core.fct_lap_position AS me_prev
        ON me_prev.session_key = me.session_key
       AND me_prev.driver_number = me.driver_number
       AND me_prev.lap_number = me.lap_number - 1
    JOIN core.fct_lap_position AS other_prev
        ON other_prev.session_key = me.session_key
       AND other_prev.lap_number = me_prev.lap_number
       AND other_prev.position < me_prev.position
    WHERE NOT EXISTS (
        SELECT 1 FROM core.fct_lap_position AS o
        WHERE o.session_key = me.session_key
          AND o.driver_number = other_prev.driver_number
          AND o.lap_number = me.lap_number
    )
    GROUP BY me.session_key, me.driver_number
),
-- Cars ahead at the end of this lap that have no row for the previous lap (a lap
-- missing in the source data); counted against the driver.
appeared_ahead AS (
    SELECT me.session_key, me.driver_number, count(*) AS n
    FROM core.fct_lap_position AS me
    JOIN core.fct_lap_position AS me_prev
        ON me_prev.session_key = me.session_key
       AND me_prev.driver_number = me.driver_number
       AND me_prev.lap_number = me.lap_number - 1
    JOIN core.fct_lap_position AS other
        ON other.session_key = me.session_key
       AND other.lap_number = me.lap_number
       AND other.position < me.position
    WHERE NOT EXISTS (
        SELECT 1 FROM core.fct_lap_position AS o
        WHERE o.session_key = me.session_key
          AND o.driver_number = other.driver_number
          AND o.lap_number = me_prev.lap_number
    )
    GROUP BY me.session_key, me.driver_number
),
-- The driver's own position change across a lap missing in the source data.
missing_lap AS (
    SELECT session_key, driver_number, sum(prev_position - position) AS n
    FROM (
        SELECT
            session_key,
            driver_number,
            lap_number,
            position,
            lag(lap_number) OVER w AS prev_lap,
            lag(position) OVER w AS prev_position
        FROM core.fct_lap_position
        WINDOW w AS (PARTITION BY session_key, driver_number ORDER BY lap_number)
    ) AS l
    WHERE prev_lap <> lap_number - 1
    GROUP BY session_key, driver_number
),
stops AS (
    SELECT
        session_key,
        driver_number,
        count(*) AS n_stops,
        count(*) FILTER (WHERE is_under_neutralisation) AS n_stops_under_neutralisation,
        round(sum(pit_loss_s) FILTER (WHERE NOT is_under_neutralisation)::numeric, 1)
            AS green_pit_loss_s
    FROM core.fct_pit_stop
    WHERE is_real_stop
    GROUP BY session_key, driver_number
),
tyres AS (
    SELECT
        session_key,
        driver_number,
        round(avg(deg_s_per_lap)::numeric, 3) AS avg_deg_s_per_lap,
        max(stint_length) AS longest_stint
    FROM core.fct_stint
    GROUP BY session_key, driver_number
),
undercuts AS (
    SELECT
        session_key,
        driver_number,
        count(*) AS n_undercut_attempts,
        count(*) FILTER (WHERE is_success) AS n_undercut_successes
    FROM core.fct_undercut_attempt
    GROUP BY session_key, driver_number
),
outcome AS (
    SELECT
        r.*,
        lap1.position AS lap1_position,
        ll.last_lap,
        ll.last_lap_position,
        r.finish_position IS NOT NULL AND r.grid_position IS NOT NULL AND NOT r.dsq
            AND lap1.position IS NOT NULL AS is_split
    FROM core.fct_race_result AS r
    LEFT JOIN core.fct_lap_position AS lap1
        ON lap1.session_key = r.session_key
       AND lap1.driver_number = r.driver_number
       AND lap1.lap_number = 1
    LEFT JOIN last_lap AS ll
        ON ll.session_key = r.session_key AND ll.driver_number = r.driver_number
)
SELECT
    o.session_key,
    o.season,
    o.circuit_short_name,
    o.driver_number,
    o.name_acronym,
    o.team_name,
    o.grid_position,
    o.finish_position,
    o.dnf,
    o.points,
    o.positions_gained,
    -- The split of positions_gained (see the header).
    CASE WHEN o.is_split THEN o.grid_position - o.lap1_position END AS gained_lap1,
    CASE WHEN o.is_split THEN coalesce(track.net, 0) END AS gained_on_track,
    CASE WHEN o.is_split THEN coalesce(pit.net, 0) END AS gained_in_pits,
    CASE WHEN o.is_split THEN
        coalesce(neut.net, 0)
        + coalesce(ra.n, 0)
        - coalesce(aa.n, 0)
        + coalesce(ml.n, 0)
        + (o.last_lap_position - o.finish_position)
    END AS gained_other,
    -- What the driver did.
    o.strategy,
    coalesce(st.n_stops, 0) AS n_stops,
    coalesce(st.n_stops_under_neutralisation, 0) AS n_stops_under_neutralisation,
    st.green_pit_loss_s,
    ty.avg_deg_s_per_lap,
    ty.longest_stint,
    coalesce(uc.n_undercut_attempts, 0) AS n_undercut_attempts,
    coalesce(uc.n_undercut_successes, 0) AS n_undercut_successes
FROM outcome AS o
LEFT JOIN swaps AS track
    ON track.session_key = o.session_key AND track.driver_number = o.driver_number
   AND track.cause = 'on_track'
LEFT JOIN swaps AS pit
    ON pit.session_key = o.session_key AND pit.driver_number = o.driver_number
   AND pit.cause = 'pit'
LEFT JOIN swaps AS neut
    ON neut.session_key = o.session_key AND neut.driver_number = o.driver_number
   AND neut.cause = 'neutralised'
LEFT JOIN retired_ahead AS ra
    ON ra.session_key = o.session_key AND ra.driver_number = o.driver_number
LEFT JOIN appeared_ahead AS aa
    ON aa.session_key = o.session_key AND aa.driver_number = o.driver_number
LEFT JOIN missing_lap AS ml
    ON ml.session_key = o.session_key AND ml.driver_number = o.driver_number
LEFT JOIN stops AS st
    ON st.session_key = o.session_key AND st.driver_number = o.driver_number
LEFT JOIN tyres AS ty
    ON ty.session_key = o.session_key AND ty.driver_number = o.driver_number
LEFT JOIN undercuts AS uc
    ON uc.session_key = o.session_key AND uc.driver_number = o.driver_number;

CREATE UNIQUE INDEX ON marts.mart_race_outcome (session_key, driver_number);
CREATE INDEX ON marts.mart_race_outcome (circuit_short_name, season);
