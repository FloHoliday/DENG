# ADR 0006: Race-only scope, car_data per driver, starting_grid via qualifying

**Context.** The use case (tyre strategy and overtaking in races) needs race
data only. Telemetry is the dominant volume. Phase 0 checked how `car_data`
and `starting_grid` behave (see `docs/api-notes.md`).

**Decision.**
- **Race only:** select `session_name = 'Race'`. Never select on `session_type`, because the Sprint has `session_type = 'Race'` too. Cancelled sessions and meetings are excluded. Sprint was dropped to halve requests and volume.
- **`car_data` per driver:** `chunk_key = "driver=<n>"`. A whole race returns 422 "too much data". One driver is ~33k rows / 5.5 MB in ~2 s, so no time-window sub-chunking is needed. The driver list comes from the stored `drivers` file, so `car_data` is planned only once `drivers` is `done`.
- **`starting_grid` via the qualifying key:** the race key returns 404, and the qualifying key of the same meeting returns the grid (rows carry the qualifying `session_key`). The raw path uses the race key, and the manifest records `queried_session_key`.

**Alternatives.**
- Also Sprint and qualifying: more data, but outside the use case.
- Try the race key first, then fall back to qualifying: one wasted request per race, now that we know the race key never works.
- `location` telemetry: very large and not needed.

**Consequences.**
- ~30 requests per race (plus 8 for the metadata refresh).
- If OpenF1 starts keying grids on the race session, the grid unit goes `failed`/`empty`, and that shows up in `status`.
- Pit-lane starters can be missing from the grid (a known gap).
