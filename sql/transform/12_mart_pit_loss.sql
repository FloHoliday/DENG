-- Mart 3: what does a pit stop cost at a circuit, and when do teams usually stop?
-- Grain: (circuit_short_name, season). Only real stops count (no penalties, no red-flag
-- pit lane). Pit loss uses green-flag stops only, because a stop under Safety Car or VSC
-- costs much less.
CREATE MATERIALIZED VIEW marts.mart_pit_loss AS
SELECT
    circuit_short_name,
    season,
    count(*) AS n_stops,
    count(*) FILTER (WHERE NOT is_under_neutralisation) AS n_green_stops,
    round((percentile_cont(0.5) WITHIN GROUP (ORDER BY lane_duration_s)
        FILTER (WHERE NOT is_under_neutralisation))::numeric, 1) AS median_lane_duration_s,
    round((percentile_cont(0.5) WITHIN GROUP (ORDER BY pit_loss_s)
        FILTER (WHERE NOT is_under_neutralisation))::numeric, 1) AS median_pit_loss_s,
    round((percentile_cont(0.5) WITHIN GROUP (ORDER BY stop_duration_s))::numeric, 1)
        AS median_stationary_s,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY lap_number) FILTER (WHERE stop_number = 1)
        AS median_first_stop_lap,
    round(count(*)::numeric / count(DISTINCT (session_key, driver_number)), 2)
        AS avg_stops_per_driver
FROM core.fct_pit_stop
WHERE is_real_stop
GROUP BY circuit_short_name, season;

CREATE UNIQUE INDEX ON marts.mart_pit_loss (circuit_short_name, season);
