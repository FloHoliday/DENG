-- Verification queries (briefing §9). Run:
--   docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < scripts/verify.sql
-- Every check marked "expect: 0 rows" lists only problems.
\set session_key 9839
\pset footer off

\echo '== 1. Rows per raw table for the review session'
SELECT 'drivers' AS tbl, count(*) FROM raw.drivers WHERE _race_session_key = :session_key
UNION ALL SELECT 'laps', count(*) FROM raw.laps WHERE _race_session_key = :session_key
UNION ALL SELECT 'stints', count(*) FROM raw.stints WHERE _race_session_key = :session_key
UNION ALL SELECT 'pit', count(*) FROM raw.pit WHERE _race_session_key = :session_key
UNION ALL SELECT 'position', count(*) FROM raw.position WHERE _race_session_key = :session_key
UNION ALL SELECT 'race_control', count(*) FROM raw.race_control WHERE _race_session_key = :session_key
UNION ALL SELECT 'session_result', count(*) FROM raw.session_result WHERE _race_session_key = :session_key
UNION ALL SELECT 'weather', count(*) FROM raw.weather WHERE _race_session_key = :session_key
UNION ALL SELECT 'intervals', count(*) FROM raw.intervals WHERE _race_session_key = :session_key
UNION ALL SELECT 'starting_grid', count(*) FROM raw.starting_grid WHERE _race_session_key = :session_key
UNION ALL SELECT 'car_data', count(*) FROM raw.car_data WHERE _race_session_key = :session_key;

\echo '== 2. Reconciliation: load_state.row_count vs rows in the table (expect: 0 rows)'
WITH actual AS (
  SELECT 'meetings' AS endpoint, _race_session_key AS key, count(*) AS n FROM raw.meetings GROUP BY 2
  UNION ALL SELECT 'sessions', _race_session_key, count(*) FROM raw.sessions GROUP BY 2
  UNION ALL SELECT 'drivers', _race_session_key, count(*) FROM raw.drivers GROUP BY 2
  UNION ALL SELECT 'laps', _race_session_key, count(*) FROM raw.laps GROUP BY 2
  UNION ALL SELECT 'stints', _race_session_key, count(*) FROM raw.stints GROUP BY 2
  UNION ALL SELECT 'pit', _race_session_key, count(*) FROM raw.pit GROUP BY 2
  UNION ALL SELECT 'position', _race_session_key, count(*) FROM raw.position GROUP BY 2
  UNION ALL SELECT 'race_control', _race_session_key, count(*) FROM raw.race_control GROUP BY 2
  UNION ALL SELECT 'session_result', _race_session_key, count(*) FROM raw.session_result GROUP BY 2
  UNION ALL SELECT 'weather', _race_session_key, count(*) FROM raw.weather GROUP BY 2
  UNION ALL SELECT 'intervals', _race_session_key, count(*) FROM raw.intervals GROUP BY 2
  UNION ALL SELECT 'starting_grid', _race_session_key, count(*) FROM raw.starting_grid GROUP BY 2
  UNION ALL SELECT 'car_data', _race_session_key, count(*) FROM raw.car_data GROUP BY 2
)
SELECT l.endpoint, l.race_session_key, l.row_count AS load_state_rows, coalesce(a.n, 0) AS table_rows
FROM meta.load_state l
LEFT JOIN actual a ON a.endpoint = l.endpoint AND a.key = l.race_session_key
WHERE l.row_count <> coalesce(a.n, 0);

\echo '== 3a. Extract units by endpoint and status'
SELECT endpoint, status, count(*) AS units FROM meta.extract_state GROUP BY 1, 2 ORDER BY 1, 2;

\echo '== 3b. Failed / deferred units (expect: 0 rows after a clean run)'
SELECT endpoint, race_session_key, chunk_key, status, http_status, last_error
FROM meta.extract_state WHERE status IN ('failed', 'deferred') ORDER BY 2, 1, 3;

\echo '== 4a. Drivers per race outside 18-22 (expect: 0 rows)'
SELECT _race_session_key, count(DISTINCT driver_number) AS drivers
FROM raw.drivers GROUP BY 1 HAVING count(DISTINCT driver_number) NOT BETWEEN 18 AND 22;

\echo '== 4b. Drivers missing from the starting grid (pit-lane starters are a known gap)'
SELECT d._race_session_key, d.driver_number, d.name_acronym
FROM raw.drivers d
WHERE NOT EXISTS (
  SELECT 1 FROM raw.starting_grid g
  WHERE g._race_session_key = d._race_session_key AND g.driver_number = d.driver_number
)
ORDER BY 1, 2;

\echo '== 4c. car_data out of range: speed 0-400, throttle 0-100, n_gear 0-8'
\echo '       (expect 0, except bad_throttle: OpenF1 sends throttle = 104 for ~3% of samples, see docs/api-notes.md)'
SELECT count(*) FILTER (WHERE speed NOT BETWEEN 0 AND 400) AS bad_speed,
       count(*) FILTER (WHERE throttle NOT BETWEEN 0 AND 100) AS bad_throttle,
       count(*) FILTER (WHERE n_gear NOT BETWEEN 0 AND 8) AS bad_gear
FROM raw.car_data WHERE _race_session_key = :session_key;

\echo '== 4d. Duplicate (driver_number, lap_number) in laps (expect: 0 rows)'
SELECT _race_session_key, driver_number, lap_number, count(*)
FROM raw.laps GROUP BY 1, 2, 3 HAVING count(*) > 1;
