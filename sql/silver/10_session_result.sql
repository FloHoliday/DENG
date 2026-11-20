SELECT
    session_key,
    driver_number,
    position AS finish_position,
    number_of_laps,
    points,
    coalesce(dnf, false) AS dnf,
    coalesce(dns, false) AS dns,
    coalesce(dsq, false) AS dsq,
    CASE WHEN gap_to_leader RLIKE '^[0-9.]+$' THEN CAST(gap_to_leader AS DOUBLE) END
        AS gap_to_leader_s,
    CAST(nullif(regexp_extract(gap_to_leader, '^[+]([0-9]+) LAP', 1), '') AS INT)
        AS laps_behind_leader
FROM bronze_session_result
