-- gap_to_leader / interval are seconds or '+N LAP(S)': split into seconds and laps.
SELECT
    session_key,
    driver_number,
    date,
    CASE WHEN gap_to_leader RLIKE '^[0-9.]+$' THEN CAST(gap_to_leader AS DOUBLE) END
        AS gap_to_leader_s,
    CASE WHEN `interval` RLIKE '^[0-9.]+$' THEN CAST(`interval` AS DOUBLE) END AS interval_s,
    CAST(nullif(regexp_extract(gap_to_leader, '^[+]([0-9]+) LAP', 1), '') AS INT)
        AS laps_behind_leader
FROM bronze_intervals
