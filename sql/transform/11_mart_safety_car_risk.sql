-- Mart 2: how likely is a neutralisation (a cheap pit stop) at a circuit, and when?
-- Grain: circuit_short_name, over all loaded seasons.
CREATE MATERIALIZED VIEW marts.mart_safety_car_risk AS
WITH races AS (
    SELECT
        s.session_key,
        s.circuit_short_name,
        s.season,
        (SELECT max(lap_number) FROM core.fct_lap AS l WHERE l.session_key = s.session_key)
            AS total_laps
    FROM staging.stg_sessions AS s
    WHERE s.is_race
      AND EXISTS (SELECT 1 FROM core.fct_lap AS l WHERE l.session_key = s.session_key)
),
per_race AS (
    SELECT
        r.session_key,
        r.circuit_short_name,
        r.season,
        r.total_laps,
        count(n.*) FILTER (WHERE n.kind = 'SC') AS n_sc,
        count(n.*) FILTER (WHERE n.kind = 'VSC') AS n_vsc,
        count(n.*) FILTER (WHERE n.kind = 'RED') AS n_red,
        min(n.start_lap) AS first_neutralisation_lap,
        coalesce(sum(n.end_lap - n.start_lap + 1), 0) AS neutralised_laps
    FROM races AS r
    LEFT JOIN core.fct_neutralisation AS n USING (session_key)
    GROUP BY r.session_key, r.circuit_short_name, r.season, r.total_laps
)
SELECT
    circuit_short_name,
    count(*) AS n_races,
    string_agg(DISTINCT season::text, ', ') AS seasons,
    count(*) FILTER (WHERE n_sc > 0) AS races_with_sc,
    count(*) FILTER (WHERE n_vsc > 0) AS races_with_vsc,
    count(*) FILTER (WHERE n_red > 0) AS races_with_red_flag,
    round(avg((n_sc + n_vsc + n_red > 0)::integer)::numeric, 2) AS neutralisation_probability,
    round(avg(n_sc + n_vsc + n_red)::numeric, 1) AS avg_neutralisations_per_race,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY first_neutralisation_lap)
        AS median_first_neutralisation_lap,
    round(sum(neutralised_laps)::numeric / sum(total_laps), 3) AS neutralised_lap_share
FROM per_race
GROUP BY circuit_short_name;

CREATE UNIQUE INDEX ON marts.mart_safety_car_risk (circuit_short_name);
