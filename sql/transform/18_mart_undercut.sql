-- Mart 7: does the undercut work at a circuit?
-- Grain: (circuit_short_name, season). See core.fct_undercut_attempt for the definition.
CREATE MATERIALIZED VIEW marts.mart_undercut AS
SELECT
    circuit_short_name,
    season,
    count(*) AS n_attempts,
    count(*) FILTER (WHERE is_success) AS n_successful,
    round(avg(is_success::integer)::numeric, 2) AS success_rate
FROM core.fct_undercut_attempt
GROUP BY circuit_short_name, season;

CREATE UNIQUE INDEX ON marts.mart_undercut (circuit_short_name, season);
