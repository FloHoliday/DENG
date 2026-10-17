-- Telemetry mart: how much slow-corner speed and lap time does a tyre lose with age?
-- Grain: (circuit_short_name, season, compound, tyre_age). Every lap is compared with the
-- first 3 clean laps of its own stint, so driver and car differences cancel out.
-- The fuel effect is still in the speeds (a lighter car is faster in corners too).
CREATE MATERIALIZED VIEW marts.mart_grip_loss AS
WITH laps AS (
    SELECT
        l.session_key,
        l.driver_number,
        l.stint_number,
        l.circuit_short_name,
        l.season,
        l.compound,
        l.tyre_age,
        l.fuel_corrected_lap_s,
        t.p10_speed_kmh,
        row_number() OVER (
            PARTITION BY l.session_key, l.driver_number, l.stint_number ORDER BY l.lap_number
        ) AS clean_lap_in_stint
    FROM core.fct_lap AS l
    JOIN core.fct_lap_telemetry AS t USING (session_key, driver_number, lap_number)
    WHERE l.is_clean_lap AND l.is_slick
),
baseline AS (
    SELECT
        session_key,
        driver_number,
        stint_number,
        avg(p10_speed_kmh) AS base_p10_speed_kmh,
        avg(fuel_corrected_lap_s) AS base_lap_s
    FROM laps
    WHERE clean_lap_in_stint <= 3
    GROUP BY session_key, driver_number, stint_number
)
SELECT
    l.circuit_short_name,
    l.season,
    l.compound,
    l.tyre_age,
    count(*) AS n_laps,
    round(avg(l.p10_speed_kmh - b.base_p10_speed_kmh)::numeric, 2) AS p10_speed_delta_kmh,
    round(avg(l.fuel_corrected_lap_s - b.base_lap_s)::numeric, 3) AS lap_time_delta_s
FROM laps AS l
JOIN baseline AS b USING (session_key, driver_number, stint_number)
GROUP BY l.circuit_short_name, l.season, l.compound, l.tyre_age;

CREATE UNIQUE INDEX ON marts.mart_grip_loss (circuit_short_name, season, compound, tyre_age);
