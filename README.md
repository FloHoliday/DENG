# F1 Race Strategy & Overtaking Analytics - End-to-End Batch Pipeline

DENG HS26 - Florian Item & Florian Leimer

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

**Data product:** a curated, queryable table (or small set of tables) at **one row per driver per lap per session**,
enriched with tyre compound and
age, weather at that point in the race, safety-car/flag status, and
lap-level aggregates of car telemetry (avg. throttle, % time at full
throttle, max speed, brake-event count; Race session only). Supporting tables cover pit stops,
stints, and session results. This supports both descriptive analysis (degradation curves, overtaking-difficulty index
per circuit) and a stretch
ML use case (predicting the optimal pit-stop lap or lap time from stint
age + conditions).

## 2. Data source

- **Source:** [OpenF1 API](https://openf1.org/docs/) — free, unofficial,
  community-run REST API for Formula 1 data. Not affiliated with the F1
  companies.
- **Access method:** HTTP GET, JSON or CSV (`csv=true`), no authentication
  required for historical data (2023 season onward). Filterable by session,
  driver, and other attributes via query parameters. **Exception:** while any live F1 session (practice, qualifying,
  sprint or
  race) is in progress, access to **everything** is denied without a paid API
  key — including all historical data (HTTP 401 "Live F1 session in
  progress"). Free access returns once the session has ended.
- **Sessions used:** only the **Race** and **Sprint** sessions of a race
  weekend. Practice and qualifying laps are not used (the qualifying result
  only enters through `starting_grid`).
- **Endpoints used:**
    - `meetings`, `sessions` — look up the race weekend and its `session_key`s
    - `drivers` — driver ↔ team mapping (`dim_driver`, `dim_team`)
    - `laps` — lap duration, sector times, per-lap grain (core fact table)
    - `stints` — tyre compound, stint start/end lap, tyre age (degradation)
    - `pit` — pit stop lap and duration (pit window / undercut)
    - `position` — position changes over time, source for derived overtakes
    - `intervals` — gap to the car ahead (was an undercut within pit-loss range?)
    - `race_control` — flags and safety car, to exclude neutralised laps
    - `weather` — ~1 row/minute, track/air temperature, rainfall (degradation)
    - `session_result`, `starting_grid` — final classification vs. grid
      position. OpenF1 keys the grid on the *qualifying* session, so it is
      fetched from there and stored next to the Race/Sprint it belongs to.
    - `car_data` — high-frequency telemetry (~3.7 Hz per car), **Race session
      only**, fetched per driver and aggregated to lap grain during
      transformation
- **Not used:** `location` (no reliable lateral reference, very large),
  `overtakes` (incomplete; derived from `position` instead), `team_radio`
  (coverage dropped sharply in 2026), all practice/qualifying laps.
- **Schema characteristics:** flat JSON records per endpoint, joinable via
  `session_key`, `meeting_key`, and `driver_number`. No documented schema
  versioning; field presence has changed release-to-release historically (e.g. `team_radio` coverage dropped sharply
  from 2026 onward).
- **Update frequency:** new sessions/meetings appear as each 2026 race
  weekend happens, so the source grows throughout the semester. Data for
  completed sessions is static once published.
- **Volume:** most endpoints are tens to a few thousand rows per session (e.g. 2025 Austin Race: ~1,000 laps, ~20,000
  intervals). `car_data` is the
  only high-volume input at ~30,000+ rows per driver for a race (~120 MB of
  raw JSON per race weekend) — the reason lap-level aggregation is planned
  rather than storing raw telemetry in the curated layer.
- **Known data-quality risks:**
    - DRS status codes (2, 3, 9, 12, 14) are not fully documented/understood.
    - `overtakes` endpoint may be incomplete during races — overtakes will
      instead be derived from `position`/lap data as a more reliable source.
    - `location` has no reliable left/right lateral reference; origin point
      is arbitrary per circuit.
    - `team_radio` coverage decreased sharply starting in 2026 — not used as
      a core input.
    - Rate limit of **3 requests/second** (HTTP 429 when exceeded, observed
      also under sustained load); the fetch script throttles and retries with
      backoff.
    - While a live F1 session is running, OpenF1 blocks **all** unauthenticated
      requests (HTTP 401, including historical data) until it ends. Fetching
      must be scheduled outside live sessions (or use a paid API key); the
      fetch script aborts with the API's message in that case.
    - Telemetry cannot be requested for a whole session at once (HTTP 422
      "too much data"); it has to be fetched per driver.
    - Historical seasons (2023–2025) are static; 2026 is live and partially
      incomplete for the remainder of the season — must decide a cutoff for
      "final" analysis vs. what gets backfilled incrementally.

### Fetching the data

Fetching means downloading from the OpenF1 API and saving the responses
unchanged as raw JSON files. It does not touch the database; loading the
files into the database is [ingestion](#3-initial-ingestion-and-storage-strategy).

- **Script:** `data/fetch_race_weekend.py` downloads the Race and Sprint
  sessions of one race weekend (meeting) into `data/raw`, one JSON file per
  endpoint/session.
- **Failure behaviour:** requests are throttled and retried with
  exponential backoff (429, 5xx, timeouts). A session folder gets a
  `_SUCCESS` marker (timestamp + row counts) only after all its endpoints
  were downloaded; the script exits non-zero otherwise. Already-downloaded
  files are skipped on re-run, so a failed fetch is resumed simply by running
  it again (`--force` forces a re-fetch).

```bash
uv sync

# by year + name (substring of meeting name, location, country or circuit)
uv run data/fetch_race_weekend.py --year 2025 --meeting "monza"

# by year only: pick the meeting from a list
uv run data/fetch_race_weekend.py --year 2025

# or by OpenF1 meeting_key
uv run data/fetch_race_weekend.py --meeting-key 1268
```

| Flag               | Meaning                                  |
|--------------------|------------------------------------------|
| `--skip-telemetry` | don't fetch `car_data` (fast run, ~15 s) |
| `--out-dir`     | target directory (default `data/raw`)    |
| `--force`          | re-fetch files that already exist        |

If the name matches more than one meeting (e.g. `italy` → Imola and Monza),
the script lists the candidates and asks which one to fetch; if it matches
none, it lists all meetings of that year. When not run interactively (e.g.
from an orchestrator) it exits with the list instead — use `--meeting-key`
there.

> **Note:** during a live F1 session (any practice, qualifying, sprint or
> race) OpenF1 denies access to all data, including past seasons. The script
> then stops with `OpenF1 access denied: Live F1 session in progress…` —
> simply run it again after the session has ended. Output layout:

```
data/raw/2025/1268_monza/
├─ meeting.json
├─ sessions.json
└─ 9912_race/
   ├─ drivers.json  laps.json  stints.json  pit.json  position.json
   ├─ intervals.json  race_control.json  weather.json
   ├─ session_result.json  starting_grid.json
   ├─ car_data/driver_<n>.json      (Race only)
   └─ _SUCCESS
```

## 3. Initial ingestion and storage strategy

Ingestion means loading the fetched raw JSON (see
[Fetching the data](#fetching-the-data)) unchanged into the database's
raw/staging layer, which transformation then builds on. Not implemented yet.

- **Ingestion mode:** batch, triggered per race weekend (meeting) after its
  fetch has completed.
- **Full vs. incremental:** incremental by session. Historical seasons
  (2023–2025) are ingested once as a full backfill since they are static;
  the 2026 season is ingested incrementally as new sessions complete,
  keyed on `session_key`/`meeting_key` so re-runs are idempotent
  (upsert/overwrite-by-key rather than blind append).
- **Local storage (midterm):** raw JSON from `data/raw` is loaded into
  PostgreSQL as a raw/staging layer before transformation.
- **Cloud storage (final):** raw JSON lands in Google Cloud Storage
  (partitioned by `year/meeting/session/endpoint`), is loaded into a BigQuery
  raw dataset and transformed into curated BigQuery tables. Local storage is
  used only for development/testing, never as a dependency of the production
  path.
- **Failure behaviour (planned):** only session folders with a `_SUCCESS`
  marker are ingested, so incomplete downloads never reach the database;
  each session is loaded in one transaction.

## 4. Architecture v0.1

```
OpenF1 API
   │  (batch HTTP GET, per session_key)
   ▼
Fetch (data/fetch_race_weekend.py)
   │  raw JSON per endpoint/session, unchanged
   ▼
Raw files
   ├─ local: data/raw on the filesystem                [midterm]
   └─ cloud: Google Cloud Storage (raw zone)           [final]
   │
   ▼
Ingestion (Python, [TBD])
   │  load complete sessions (_SUCCESS), upsert by key
   ▼
Raw/staging tables
   ├─ local: PostgreSQL staging schema                 [midterm]
   └─ cloud: BigQuery raw dataset                      [final]
   │
   ▼
Transformation (planned: dbt or plain SQL/Python — [TBD])
   │  clean, join on session/driver keys, aggregate
   │  car_data to lap grain
   ▼
Curated layer
   ├─ local: PostgreSQL                                [midterm]
   └─ cloud: BigQuery curated dataset                   [final]
        - fact_laps (grain: 1 row per driver/lap/session)
        - fact_pit_stops, fact_stints
        - dim_driver, dim_team, dim_session, dim_circuit
   │
   ▼
Orchestration: [TBD — e.g. Airflow/Dagster] schedules fetch → ingestion →
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
- Exact partitioning/clustering plan for BigQuery (likely partition by
  session date, cluster by `session_key`/`driver_number`).

## 6. Project plan / backlog (Week 3 → Week 7)

- [ ] Confirm team roles and split fetch/ingestion vs. transformation ownership
- [x] Write fetch script for one race weekend (`data/fetch_race_weekend.py`)
- [ ] Stand up local PostgreSQL + Docker Compose environment
- [ ] Write ingestion: load `data/raw` (sessions with `_SUCCESS`) into
  PostgreSQL staging tables
- [ ] Lap-level aggregation of `car_data`
- [ ] Define and implement first justified transformation (lap-grain fact
  table with tyre/weather/safety-car enrichment)
- [ ] Pick and configure orchestrator; wire up fetch → ingestion → transformation
  with rerun/backfill support
- [ ] Draft Architecture v0.2 reflecting implementation decisions
- [ ] Write setup, execution, and verification instructions for midterm

## 7. Repository structure [TBD — update as it firms up]

```
/data           - fetch script: OpenF1 API → raw JSON (fetch_race_weekend.py)
/data/raw       - raw JSON downloaded by the fetch (gitignored)
/ingestion      - loads data/raw into the database (planned)
/transform      - cleaning/aggregation/modeling logic
/orchestration  - DAGs / pipeline definitions
/infra          - Terraform (final milestone)
/docs           - architecture diagrams, decisions
README.md
.env.example
```

## 8. Limitations (known so far)

- OpenF1 is an unofficial, community-maintained API with no SLA and a
  3 requests/second rate limit; fetch reliability depends on its uptime.
- The free API is completely unavailable during live F1 sessions (all
  endpoints, including historical data), so fetching can only run outside
  session times unless a paid API key is used.
- 2026 season data is incomplete until the season ends; season-level
  comparisons will be partial for now.
- DRS and lateral-position telemetry fields have documented ambiguity and
  are not used for quantitative conclusions without caveats.