-- Telemetry mart: what kind of circuit is it, and why is it hard on tyres?
-- Grain: (circuit_short_name, season), clean laps only.
CREATE MATERIALIZED VIEW marts.mart_circuit_character AS
SELECT
    l.circuit_short_name,
    l.season,
    count(*) AS n_laps,
    round((percentile_cont(0.5) WITHIN GROUP (ORDER BY l.lap_duration_s))::numeric, 3)
        AS median_clean_lap_s,
    round(avg(t.full_throttle_pct)::numeric, 1) AS full_throttle_pct,
    round(avg(t.brake_events)::numeric, 1) AS brake_events_per_lap,
    round(avg(t.top_speed_kmh)::numeric, 1) AS avg_top_speed_kmh,
    round(avg(t.p10_speed_kmh)::numeric, 1) AS avg_p10_speed_kmh,
    round(avg(t.lift_coast_s)::numeric, 2) AS lift_coast_s_per_lap
FROM core.fct_lap AS l
JOIN core.fct_lap_telemetry AS t USING (session_key, driver_number, lap_number)
WHERE l.is_clean_lap
GROUP BY l.circuit_short_name, l.season;

CREATE UNIQUE INDEX ON marts.mart_circuit_character (circuit_short_name, season);
