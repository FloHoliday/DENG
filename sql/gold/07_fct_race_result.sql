-- Grain: (session_key, driver_number). Grid vs. finish and the strategy that was run.
WITH strategies AS (
    SELECT
        session_key,
        driver_number,
        count(*) - 1 AS n_stops,
        -- Compound sequence, e.g. M-H or S-M-H (I = intermediate, W = wet, U = unknown).
        array_join(
            transform(
                array_sort(collect_list(struct(stint_number, compound))),
                x -> left(x.compound, 1)
            ),
            '-'
        ) AS strategy
    FROM fct_stint
    GROUP BY session_key, driver_number
)
SELECT
    r.session_key,
    s.season,
    s.circuit_short_name,
    r.driver_number,
    d.name_acronym,
    d.team_name,
    g.grid_position,
    r.finish_position,
    g.grid_position - r.finish_position AS positions_gained,
    r.points,
    r.dnf,
    r.dns,
    r.dsq,
    coalesce(st.n_stops, 0) AS n_stops,
    coalesce(st.strategy, 'UNKNOWN') AS strategy
FROM silver_session_result AS r
JOIN silver_sessions AS s USING (session_key)
LEFT JOIN silver_drivers AS d USING (session_key, driver_number)
LEFT JOIN silver_starting_grid AS g USING (session_key, driver_number)
LEFT JOIN strategies AS st USING (session_key, driver_number)
WHERE s.is_race
