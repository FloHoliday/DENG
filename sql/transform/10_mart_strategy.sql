-- Mart 1: which strategies were run at a circuit, and how did they work out?
-- Grain: (circuit_short_name, season, strategy).
CREATE SCHEMA IF NOT EXISTS marts;

CREATE MATERIALIZED VIEW marts.mart_strategy_per_circuit AS
SELECT
    circuit_short_name,
    season,
    strategy,
    max(n_stops) AS n_stops,
    count(*) AS n_drivers,
    count(*) FILTER (WHERE dnf) AS n_dnf,
    round(avg(positions_gained) FILTER (WHERE NOT dnf)::numeric, 1) AS avg_positions_gained,
    round(avg(finish_position) FILTER (WHERE NOT dnf)::numeric, 1) AS avg_finish_position,
    min(finish_position) AS best_finish_position,
    count(*) FILTER (WHERE points > 0) AS n_points_finishes
FROM core.fct_race_result
WHERE NOT dns
GROUP BY circuit_short_name, season, strategy;

CREATE UNIQUE INDEX ON marts.mart_strategy_per_circuit (circuit_short_name, season, strategy);
