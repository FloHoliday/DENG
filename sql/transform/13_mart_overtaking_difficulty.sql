-- Mart 4: is track position or tyre offset worth more at a circuit?
-- Grain: (circuit_short_name, season). Few on-track passes and a high grid/finish
-- correlation mean qualifying and track position decide the race.
CREATE MATERIALIZED VIEW marts.mart_overtaking_difficulty AS
WITH passes AS (
    SELECT session_key, count(*) AS n_passes
    FROM core.fct_on_track_pass
    GROUP BY session_key
),
grid_vs_finish AS (
    SELECT
        session_key,
        circuit_short_name,
        season,
        corr(grid_position, finish_position) FILTER (WHERE NOT dnf AND NOT dsq)
            AS grid_finish_correlation,
        avg(abs(positions_gained)) FILTER (WHERE NOT dnf AND NOT dsq)
            AS avg_abs_positions_changed
    FROM core.fct_race_result
    GROUP BY session_key, circuit_short_name, season
)
SELECT
    g.circuit_short_name,
    g.season,
    count(*) AS n_races,
    round(avg(coalesce(p.n_passes, 0))::numeric, 1) AS avg_on_track_passes,
    round(avg(g.grid_finish_correlation)::numeric, 2) AS grid_finish_correlation,
    round(avg(g.avg_abs_positions_changed)::numeric, 1) AS avg_abs_positions_changed
FROM grid_vs_finish AS g
LEFT JOIN passes AS p USING (session_key)
GROUP BY g.circuit_short_name, g.season;

CREATE UNIQUE INDEX ON marts.mart_overtaking_difficulty (circuit_short_name, season);
