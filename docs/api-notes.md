# OpenF1 API notes (Phase 0 spike)

Checked on Sat 10 Oct 2026, 19:37 UTC, with about 25 manual requests spaced at least 1 s apart. No 429 was provoked.
Review race: Abu Dhabi 2025, `meeting_key 1276`, Race `session_key 9839`, Qualifying `session_key 9835`.

## Findings on the open points (briefing §3)

| # | Question | Finding | Consequence |
|---|---|---|---|
| 1 | `starting_grid` key | `starting_grid?session_key=9839` (race) → **404** `{"detail":"No results found."}`. `starting_grid?session_key=9835` (qualifying) → 200, 20 rows, all with `session_key 9835`. | **Always query the Qualifying session of the same meeting.** No race-key attempt, so one request is saved per race. The raw path uses the race key, and the manifest's `queried_session_key` holds the qualifying key. |
| 2 | Empty result format | `laps?session_key=9839&driver_number=999` → **404** with body `{"detail":"No results found."}`, not `200 []`. | The classifier treats a 404 whose body `detail` is `"No results found."` as *empty*. Any other 404 is `failed`. The raw zone stores the body exactly as received, with `record_count 0`. |
| 3 | `car_data` size per driver × race | Driver 1 in 9839: **33,653 rows, 5.5 MB, 2.4 s**, 200. A whole session without `driver_number` → **422** `"You're likely asking for too much data at once."` after 5 s. | Per-driver chunking is enough, so there is **no time-window sub-chunking**. A 422 is not retried (it is a 4xx), so the unit gets `failed`. |
| 4 | Blackout status code | Not observable now: no session was live. The Singapore race (`meeting_key 1296`) is on 11 Oct 2026. Earlier project work saw **401** `"Live F1 session in progress"` (see the previous `fetch.py` and README). | Handle **401 and 403** the same way: `deferred` inside a live window, otherwise `failed`. 403 is still **unverified**. |
| 5 | `Retry-After` on 429 | Normal 200 responses send no rate-limit headers (`X-RateLimit-*`, `Retry-After`). No 429 was provoked. | Honour `Retry-After` if present, otherwise use exponential backoff. Unverified whether the API sends it. |

## Other observations

- Response sizes for 9839: `intervals` 26,261 rows / 3.7 MB; `laps` 1,156 rows / 0.55 MB; all other session endpoints are under 80 KB. Every response came back in under 2.5 s.
- **`session_result` has a `points` field** (float) that is missing from the briefing's field list. I added it as a `numeric` column so it does not end up in `_extra`.
- `session_result.gap_to_leader` comes back as int, float or string (`"+1 LAP"`). `duration` is null for lapped cars. Both are stored as `text`, as the briefing says.
- `intervals.gap_to_leader` can be a float, a string or null. `interval` was float or null in this race, but the docs allow strings, so both are `text`.
- `weather.rainfall` is an integer (0/1), not a boolean, so it is stored as `integer`.
- `drivers.country_code` is already `null` for every row (deprecated). `drivers.headshot_url` is sometimes null.
- `laps.segments_sector_*` are integer lists, e.g. `[2048, 2049, 2051]`, which map to `integer[]`. `duration_sector_1` and `i1_speed` are null on lap 1.
- Every timestamp carries an explicit `+00:00` offset, so it parses straight into `timestamptz`.
- The 9839 grid has 20 rows. The briefing's note about 18-row grids (missing pit-lane starters) still stands for other races and is not an error.
- 2026 Singapore weekend (`meeting_key 1296`): Sprint 10 Oct 09:00–10:00 UTC, Qualifying 10 Oct 13:30–14:30 UTC, Race 11 Oct. This weekend can be used to demo the live-window guard with `--now`.

## Design adjustments

1. `starting_grid` queries the qualifying key directly (the briefing's "if confirmed" branch).
2. Empty = `200 []` **or** `404 {"detail":"No results found."}`.
3. No `car_data` time-window chunking.
4. `raw.session_result.points numeric` was added.
