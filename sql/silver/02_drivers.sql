-- One row per driver (OpenF1 can list a driver twice).
SELECT session_key, driver_number, name_acronym, full_name, team_name
FROM (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY session_key, driver_number ORDER BY full_name, team_name
        ) AS n
    FROM bronze_drivers
)
WHERE n = 1
