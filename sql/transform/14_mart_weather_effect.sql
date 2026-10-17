-- Mart 9: does a hotter track make a compound degrade faster?
-- Grain: (season, compound, track_temp_band_c) in 5 degree bands, over all circuits.
CREATE MATERIALIZED VIEW marts.mart_weather_effect AS
SELECT
    season,
    compound,
    (floor(avg_track_temperature / 5) * 5)::integer AS track_temp_band_c,
    count(*) AS n_stints,
    round((percentile_cont(0.5) WITHIN GROUP (ORDER BY deg_s_per_lap))::numeric, 3)
        AS median_deg_s_per_lap,
    round((percentile_cont(0.5) WITHIN GROUP (ORDER BY stint_length))::numeric, 1)
        AS median_stint_length
FROM core.fct_stint
WHERE is_slick AND deg_s_per_lap IS NOT NULL AND avg_track_temperature IS NOT NULL
GROUP BY season, compound, track_temp_band_c;

CREATE UNIQUE INDEX ON marts.mart_weather_effect (season, compound, track_temp_band_c);
