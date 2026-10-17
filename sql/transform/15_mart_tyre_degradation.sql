-- Mart 5: how fast does each compound degrade at a circuit?
-- Grain: (circuit_short_name, season, compound). SOFT/MEDIUM/HARD are relative names, but
-- within one circuit and season they always stand for the same Pirelli compounds.
CREATE MATERIALIZED VIEW marts.mart_tyre_degradation AS
WITH pooled AS (
    SELECT
        circuit_short_name,
        season,
        compound,
        count(*) AS n_clean_laps,
        -- Fuel-corrected lap time on a fresh tyre (intercept at tyre age 0).
        regr_intercept(fuel_corrected_lap_s, tyre_age) AS base_pace_s
    FROM core.fct_lap
    WHERE is_clean_lap AND compound IS NOT NULL
    GROUP BY circuit_short_name, season, compound
)
SELECT
    st.circuit_short_name,
    st.season,
    st.compound,
    count(*) AS n_stints,
    count(st.deg_s_per_lap) AS n_stints_with_slope,
    max(p.n_clean_laps) AS n_clean_laps,
    round(max(p.base_pace_s)::numeric, 3) AS base_pace_s,
    -- Median of the per-stint slopes: each stint only compares a driver with their own laps.
    round((percentile_cont(0.5) WITHIN GROUP (ORDER BY st.deg_s_per_lap))::numeric, 3)
        AS deg_s_per_lap,
    max(st.stint_length) AS max_stint_observed,
    round((percentile_cont(0.5) WITHIN GROUP (ORDER BY st.stint_length))::numeric, 1)
        AS median_stint_length
FROM core.fct_stint AS st
LEFT JOIN pooled AS p USING (circuit_short_name, season, compound)
GROUP BY st.circuit_short_name, st.season, st.compound;

CREATE UNIQUE INDEX ON marts.mart_tyre_degradation (circuit_short_name, season, compound);
