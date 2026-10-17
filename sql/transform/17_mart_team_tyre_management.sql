-- Mart 8: which teams treat their tyres better than the field?
-- Grain: (season, team_name, compound). Each stint is compared with the median stint of
-- the same race and compound, so circuit differences cancel out.
CREATE MATERIALIZED VIEW marts.mart_team_tyre_management AS
WITH field AS (
    SELECT
        session_key,
        compound,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY deg_s_per_lap) AS field_deg_s_per_lap,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY stint_length) AS field_stint_length
    FROM core.fct_stint
    WHERE deg_s_per_lap IS NOT NULL
    GROUP BY session_key, compound
)
SELECT
    st.season,
    st.team_name,
    st.compound,
    count(*) AS n_stints,
    round((percentile_cont(0.5) WITHIN GROUP (
        ORDER BY st.deg_s_per_lap - f.field_deg_s_per_lap))::numeric, 3)
        AS deg_vs_field_s_per_lap,
    round(avg(st.stint_length - f.field_stint_length)::numeric, 1) AS stint_length_vs_field,
    round(avg(st.avg_lift_coast_s)::numeric, 2) AS avg_lift_coast_s_per_lap
FROM core.fct_stint AS st
JOIN field AS f USING (session_key, compound)
WHERE st.deg_s_per_lap IS NOT NULL AND st.team_name IS NOT NULL AND st.is_slick
GROUP BY st.season, st.team_name, st.compound;

CREATE UNIQUE INDEX ON marts.mart_team_tyre_management (season, team_name, compound);
