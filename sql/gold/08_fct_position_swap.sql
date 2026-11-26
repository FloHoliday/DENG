-- Grain: (session_key, lap_number, gaining_driver, losing_driver).
-- Every swap of two cars between the end of the previous lap and the end of this lap
-- (both completed both laps; lap 1 is the start, see mart_race_outcome), with its cause:
--   pit:         one of the two cars was on a pit in- or out-lap
--   neutralised: no pit, but the lap was under Safety Car, VSC or red flag
--   on_track:    a real overtake under green flag
SELECT
    a.session_key,
    a.lap_number,
    a.driver_number AS gaining_driver,
    b.driver_number AS losing_driver,
    CASE
        WHEN a.is_pit_in_lap OR a.is_pit_out_lap OR b.is_pit_in_lap OR b.is_pit_out_lap
            THEN 'pit'
        WHEN a.is_neutralised OR b.is_neutralised THEN 'neutralised'
        ELSE 'on_track'
    END AS cause
FROM fct_lap_position AS a
JOIN fct_lap_position AS a_prev
    ON a_prev.session_key = a.session_key
   AND a_prev.driver_number = a.driver_number
   AND a_prev.lap_number = a.lap_number - 1
JOIN fct_lap_position AS b
    ON b.session_key = a.session_key
   AND b.lap_number = a.lap_number
   AND b.driver_number <> a.driver_number
JOIN fct_lap_position AS b_prev
    ON b_prev.session_key = b.session_key
   AND b_prev.driver_number = b.driver_number
   AND b_prev.lap_number = b.lap_number - 1
WHERE a.lap_number > 1
  AND a_prev.position > b_prev.position
  AND a.position < b.position
