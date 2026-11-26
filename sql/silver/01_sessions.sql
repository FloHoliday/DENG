-- OpenF1 also labels Sprints session_type 'Race', so session_name decides.
SELECT
    s.session_key,
    s.meeting_key,
    s.year AS season,
    s.circuit_short_name,
    m.meeting_name,
    s.country_name,
    s.session_name,
    s.session_name = 'Race' AS is_race,
    s.date_start,
    s.date_end
FROM bronze_sessions AS s
JOIN bronze_meetings AS m USING (meeting_key)
WHERE NOT coalesce(s.is_cancelled, false)
