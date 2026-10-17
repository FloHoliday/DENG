-- Mart 6: from which tyre age does a pit stop pay off?
-- Grain: (circuit_short_name, season, compound). A tyre of age A has lost about
-- deg * A * (A + 1) / 2 seconds in total against a new one. The stop pays off once that
-- loss exceeds the pit loss: A = sqrt(2 * pit_loss / deg). A rough rule: it ignores
-- traffic, track position and the next stint's own degradation.
CREATE MATERIALIZED VIEW marts.mart_pit_window AS
SELECT
    d.circuit_short_name,
    d.season,
    d.compound,
    d.deg_s_per_lap,
    p.median_pit_loss_s,
    CASE
        WHEN d.deg_s_per_lap > 0 AND p.median_pit_loss_s > 0
        THEN ceil(sqrt(2 * p.median_pit_loss_s / d.deg_s_per_lap))::integer
    END AS break_even_tyre_age,
    d.median_stint_length,
    d.max_stint_observed,
    p.median_first_stop_lap
FROM marts.mart_tyre_degradation AS d
JOIN marts.mart_pit_loss AS p USING (circuit_short_name, season)
WHERE d.compound IN ('SOFT', 'MEDIUM', 'HARD');

CREATE UNIQUE INDEX ON marts.mart_pit_window (circuit_short_name, season, compound);
