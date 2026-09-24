# F1 Race Strategy & Overtaking Analytics — End-to-End Batch Pipeline

DENG HS26 · Data Engineering Project · Team ??? (Team members: ___, ___)

> Milestone 1 (Week 3) status: initial pitch. This README covers the required
> Week 3 content: dataset & source description, use case & user, initial
> ingestion/storage strategy, data risks, Architecture v0.1, and the project
> plan/backlog. Sections marked **[TBD]** are placeholders to fill in as the
> team decides them before the pitch.

## 1. Use case and user

**User / stakeholder:** an F1 team's race strategist (or a strategy-focused
fan analyst) who wants to understand, after each race weekend, how tyre
strategy and on-track position changes actually decided race outcomes.

**Problem:** raw lap-by-lap and telemetry data from a race weekend is too
granular and too large to reason about directly. The strategist needs a
curated view that answers two linked questions per circuit and per season:

1. How does each tyre compound degrade over a stint, and at what lap does
   the data suggest a pit stop (undercut/overtake) becomes worth it?
2. How hard is it to overtake at this circuit, and how much did grid
   position vs. race pace vs. strategy calls determine the final result?

**Data product:** a curated, queryable table (or small set of tables) at
**one row per driver per lap per session**, enriched with tyre compound and
age, weather at that point in the race, safety-car/flag status, and
lap-level aggregates of car telemetry (avg. throttle, % time at full
throttle, max speed, brake-event count). Supporting tables cover pit stops,
stints, and session results. This supports both descriptive analysis
(degradation curves, overtaking-difficulty index per circuit) and a stretch
ML use case (predicting the optimal pit-stop lap or lap time from stint
age + conditions).

## 2. Data source

- **Source:** [OpenF1 API](https://openf1.org/docs/) — free, unofficial,
  community-run REST API for Formula 1 data. Not affiliated with the F1
  companies.
- **Access method:** HTTP GET, JSON or CSV (`csv=true`), no authentication
  required for historical data (2023 season onward). Filterable by session,
  driver, and other attributes via query parameters.
- **Endpoints used (planned):**
  - `sessions`, `meetings` — session/event metadata (grain of ingestion)
  - `laps` — lap duration, sector times, per-lap grain
  - `stints` — tyre compound, stint start/end lap, tyre age
  - `pit` — pit stop duration and lap
  - `weather` — ~1 row/minute, track/air temperature, rainfall
  - `race_control` — flags, safety car, incidents
  - `session_result`, `starting_grid` — final classification, grid position
  - `car_data`, `location` — high-frequency telemetry (~3.7 Hz per car),
    aggregated down to lap grain during transformation rather than kept raw
    at full resolution, to keep volume manageable
- **Schema characteristics:** flat JSON records per endpoint, joinable via
  `session_key`, `meeting_key`, and `driver_number`. No documented schema
  versioning; field presence has changed release-to-release historically
  (e.g. `team_radio` coverage dropped sharply from 2026 onward).
- **Update frequency:** new sessions/meetings appear as each 2026 race
  weekend happens, so the source grows throughout the semester. Data for
  completed sessions is static once published.
- **Volume:** low-volume endpoints (laps, stints, pits, weather, results)
  are a few hundred to a few thousand rows per session. `car_data` and
  `location` are the outliers at roughly 250k–500k rows per car per
  session — the main reason lap-level aggregation is planned rather than
  storing raw telemetry in the curated layer.
- **Known data-quality risks:**
  - DRS status codes (2, 3, 9, 12, 14) are not fully documented/understood.
  - `overtakes` endpoint may be incomplete during races — overtakes will
    instead be derived from `position`/lap data as a more reliable source.
  - `location` has no reliable left/right lateral reference; origin point
    is arbitrary per circuit.
  - `team_radio` coverage decreased sharply starting in 2026 — not used as
    a core input.
  - No documented API rate limit; ingestion must handle timeouts/backoff
    defensively.
  - Historical seasons (2023–2025) are static; 2026 is live and partially
    incomplete for the remainder of the season — must decide a cutoff for
    "final" analysis vs. what gets backfilled incrementally.

## 3. Initial ingestion and storage strategy

- **Ingestion mode:** batch, triggered per race weekend (session-level
  grain). Each `session_key` is ingested once its session is marked
  finished in the `sessions` endpoint.
- **Full vs. incremental:** incremental by session. Historical seasons
  (2023–2025) are ingested once as a full backfill since they are static;
  the 2026 season is ingested incrementally as new sessions complete,
  keyed on `session_key`/`meeting_key` so re-runs are idempotent
  (upsert/overwrite-by-key rather than blind append).
- **Local storage (midterm):** raw JSON responses landed as-is per
  endpoint/session, then loaded into PostgreSQL as a raw/staging layer
  before transformation.
- **Cloud storage (final):** raw responses land in Google Cloud Storage
  (partitioned by `year/meeting/session/endpoint`), transformed into
  curated BigQuery tables. Local storage is used only for
  development/testing, never as a dependency of the production path.
- **Failure behaviour (planned):** per-session ingestion is retried with
  backoff on request failure; a session is only marked ingested after all
  required endpoints for it have loaded successfully, so partial failures
  are safely re-run rather than silently producing incomplete data.

## 4. Architecture v0.1

```
OpenF1 API
   │  (batch HTTP GET, per session_key)
   ▼
Ingestion script (Python)
   │  raw JSON per endpoint/session
   ▼
Raw storage
   ├─ local: filesystem → PostgreSQL staging tables   [midterm]
   └─ cloud: Google Cloud Storage (raw zone)           [final]
   │
   ▼
Transformation (planned: dbt or plain SQL/Python — [TBD])
   │  clean, join on session/driver keys, aggregate
   │  car_data/location to lap grain
   ▼
Curated layer
   ├─ local: PostgreSQL                                [midterm]
   └─ cloud: BigQuery curated dataset                   [final]
        - fact_laps (grain: 1 row per driver/lap/session)
        - fact_pit_stops, fact_stints
        - dim_driver, dim_team, dim_session, dim_circuit
   │
   ▼
Orchestration: [TBD — e.g. Airflow/Dagster] schedules ingestion →
transformation, supports retries and backfills per session
   │
   ▼
Infrastructure: Terraform provisions the GCS bucket and BigQuery dataset
```

Diagram will be replaced with a proper architecture diagram (image) before
the pitch; this is the v0.1 text sketch.

## 5. Open decisions before the pitch [TBD]

- Orchestrator choice (Airflow vs. Dagster vs. other).
- Transformation tool (dbt vs. plain SQL/Python scripts).
- Whether to keep any raw telemetry sample at full resolution for one
  demo session, vs. aggregating everything to lap grain from the start.
- Exact partitioning/clustering plan for BigQuery (likely partition by
  session date, cluster by `session_key`/`driver_number`).

## 6. Project plan / backlog (Week 3 → Week 7)

- [ ] Confirm team roles and split ingestion vs. transformation ownership
- [ ] Write ingestion script for `sessions`/`meetings` (bootstraps all
      other pulls via `session_key`)
- [ ] Write ingestion scripts for `laps`, `stints`, `pit`, `weather`,
      `race_control`, `session_result`, `starting_grid`
- [ ] Write ingestion + lap-level aggregation for `car_data`/`location`
- [ ] Stand up local PostgreSQL + Docker Compose environment
- [ ] Define and implement first justified transformation (lap-grain fact
      table with tyre/weather/safety-car enrichment)
- [ ] Pick and configure orchestrator; wire up ingestion → transformation
      with rerun/backfill support
- [ ] Draft Architecture v0.2 reflecting implementation decisions
- [ ] Write setup, execution, and verification instructions for midterm

## 7. Repository structure [TBD — update as it firms up]

```
/ingestion      - OpenF1 API pull scripts
/transform      - cleaning/aggregation/modeling logic
/orchestration  - DAGs / pipeline definitions
/infra          - Terraform (final milestone)
/docs           - architecture diagrams, decisions
README.md
.env.example
```

## 8. Limitations (known so far)

- OpenF1 is an unofficial, community-maintained API with no SLA or
  documented rate limits; ingestion reliability depends on its uptime.
- 2026 season data is incomplete until the season ends; season-level
  comparisons will be partial for now.
- DRS and lateral-position telemetry fields have documented ambiguity and
  are not used for quantitative conclusions without caveats.