-- Grain: (session_key, driver_number, lap_number) of the attacker's green-flag stop.
-- Undercut attempt: A is directly behind B at the end of the lap before A's stop, and B
-- stops 1 to 3 laps later. Success: A is ahead of B at the end of B's out-lap.
-- Both stops are real green-flag stops. If B stops more than once in that window (e.g.
-- PER at Suzuka 2023), only B's first stop counts.
SELECT
    session_key, season, circuit_short_name, driver_number, lap_number,
    defending_driver, laps_later, is_success
FROM (
    SELECT
        a_stop.session_key,
        a_stop.season,
        a_stop.circuit_short_name,
        a_stop.driver_number,
        a_stop.lap_number,
        b_stop.driver_number AS defending_driver,
        b_stop.lap_number - a_stop.lap_number AS laps_later,
        a_after.position < b_after.position AS is_success,
        row_number() OVER (
            PARTITION BY a_stop.session_key, a_stop.driver_number, a_stop.lap_number
            ORDER BY b_stop.lap_number
        ) AS n
    FROM fct_pit_stop AS a_stop
    JOIN fct_lap_position AS a_before
        ON a_before.session_key = a_stop.session_key
       AND a_before.driver_number = a_stop.driver_number
       AND a_before.lap_number = a_stop.lap_number - 1
    JOIN fct_lap_position AS b_before
        ON b_before.session_key = a_stop.session_key
       AND b_before.lap_number = a_before.lap_number
       AND b_before.position = a_before.position - 1
    JOIN fct_pit_stop AS b_stop
        ON b_stop.session_key = a_stop.session_key
       AND b_stop.driver_number = b_before.driver_number
       AND b_stop.lap_number BETWEEN a_stop.lap_number + 1 AND a_stop.lap_number + 3
       AND b_stop.is_real_stop
       AND NOT b_stop.is_under_neutralisation
    JOIN fct_lap_position AS a_after
        ON a_after.session_key = a_stop.session_key
       AND a_after.driver_number = a_stop.driver_number
       AND a_after.lap_number = b_stop.lap_number + 1
    JOIN fct_lap_position AS b_after
        ON b_after.session_key = a_stop.session_key
       AND b_after.driver_number = b_stop.driver_number
       AND b_after.lap_number = b_stop.lap_number + 1
    WHERE a_stop.is_real_stop AND NOT a_stop.is_under_neutralisation
)
WHERE n = 1
