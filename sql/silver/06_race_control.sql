-- event: the race-control messages that start or end a neutralisation.
-- lap_number is the leader's lap.
SELECT
    session_key,
    date,
    lap_number,
    category,
    flag,
    message,
    CASE
        WHEN message = 'SAFETY CAR DEPLOYED' THEN 'SC'
        WHEN message = 'VSC DEPLOYED' THEN 'VSC'
        WHEN message RLIKE '^RED FLAG' THEN 'RED'
        WHEN message = 'SAFETY CAR IN THIS LAP' THEN 'SC_END'
        WHEN message = 'VSC ENDING' THEN 'VSC_END'
        WHEN category = 'SessionStatus' AND message = 'SESSION STARTED' THEN 'START'
        WHEN flag = 'CHEQUERED' THEN 'FINISH'
    END AS event
FROM bronze_race_control
