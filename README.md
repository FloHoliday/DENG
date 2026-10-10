# F1 Race Strategy & Overtaking Analytics - End-to-End Batch Pipeline

DENG HS26 - Florian Item & Florian Leimer

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
**one row per driver per lap per race**, enriched with tyre compound and
age, weather at that point in the race, safety-car/flag status, and
lap-level aggregates of car telemetry (avg. throttle, % time at full
throttle, max speed, brake-event count). Supporting tables cover pit stops,
stints, and session results. This supports both descriptive analysis
(degradation curves, overtaking-difficulty index per circuit) and a stretch
ML use case (predicting the optimal pit-stop lap or lap time from stint
age + conditions).

## 2. Data source

- **Source:** [OpenF1 API](https://openf1.org/docs/) - free, unofficial,
  community-run REST API for Formula 1 data. Not affiliated with the F1
  companies.
- **Access method:** HTTP GET, JSON, no authentication for historical data
  (2023 onward). Rate limit 3 requests/second and 30 requests/minute.
  **Exception:** from 30 min before until 30 min after any live F1 session,
  the free API is blocked completely (HTTP 401), historical data included.
- **Sessions used:** only **Race** sessions (`session_name = 'Race'`, not
  cancelled), seasons 2023 → today. Sprint, qualifying and practice data are
  not used. The qualifying session key is used only to fetch the
  `starting_grid`, because OpenF1 keys the grid on qualifying.
- **Endpoints used:** `meetings`, `sessions` (metadata, all session types,
  needed for race discovery and the live-window guard), `drivers`, `laps`,
  `stints`, `pit`, `position`, `race_control`, `session_result`, `weather`,
  `intervals`, `starting_grid`, and `car_data` (telemetry, ~3.7 Hz, fetched
  per driver).
- **Not used:** `location` (very large, no reliable lateral reference),
  `overtakes`, `team_radio`, everything outside Race sessions.
- **Schema characteristics:** flat JSON records per endpoint, joinable via
  `session_key`, `meeting_key`, `driver_number`. Some fields are
  polymorphic (e.g. `gap_to_leader` is a number or `"+1 LAP"`). There is no
  schema versioning. Our findings are in [docs/api-notes.md](docs/api-notes.md).
- **Update frequency:** a new race every one or two weeks during the season.
  Data for a race may still change for a few days after it ends.

## 3. Pipeline

Two decoupled stages, both started by hand through one CLI (`src/cli.py`):

1. **Extract** (`src/fetch.py`): OpenF1 → **raw zone** (`data/raw`). Each
   response is stored as its exact bytes, gzip-compressed, with a
   `_manifest.json` (URL, params, HTTP status, record count, sha256, run id).
   Extract is the only code that calls the API.
2. **Load** (`src/ingest.py`): raw zone → PostgreSQL, one typed table per
   endpoint in schema `raw`. Load reads only from the raw zone, so reloading
   costs zero API calls, and an API outage can never corrupt the database.

Pipeline state lives in schema `meta`:
- `pipeline_run`: one row per command.
- `extract_state`: one row per extract unit `(endpoint, race_session_key, chunk_key)`, with status `pending | done | empty | deferred | failed`.
- `load_state`: one row per load partition `(endpoint, race_session_key)`, with a fingerprint of its files.

The architecture, grain and failure handling are described in
[docs/architecture.md](docs/architecture.md). The decisions behind them are
in [docs/decisions/](docs/decisions/).

**Failsafe and idempotent:**
- Every unit's status is committed as soon as it finishes, so a rerun continues where the last run stopped (crash, Ctrl+C, `--max-requests`).
- Units already `done`/`empty` are not fetched again, unless the race ended less than `SETTLING_DAYS` ago or `--force` is given.
- Files are written atomically (temp file + rename, data before manifest).
- A load replaces a whole partition in one transaction (DELETE + COPY). It checks that the row count matches the manifests and rolls back otherwise. A partition whose files have not changed is skipped.
- During a live window, the remaining units become `deferred` and the run stops with exit code 0. An empty response within the settling window is also `deferred`.

## 4. Setup

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Python 3.13 (uv installs it).

```bash
cp .env.example .env              # adjust POSTGRES_PASSWORD etc.
docker compose up -d postgres     # PostgreSQL 18 on 127.0.0.1:5432 (pgAdmin optional: docker compose up -d)
uv sync
uv run src/cli.py init-db         # creates schemas meta and raw (idempotent)
```

The CLI runs on the host as `uv run src/cli.py <command>`. The project has
no package, so there is no `f1` executable. Inside Docker it runs as
`docker compose run --rm code <command>`.

## 5. Commands

| Command | What it does |
|---|---|
| `init-db` | apply `sql/*.sql` (idempotent) |
| `extract [filters] [--force] [--max-requests N] [--dry-run]` | refresh metadata, then fetch all planned units into the raw zone |
| `load [filters] [--force]` | load completed partitions into `raw.*` (no API calls) |
| `run [filters] [--force] [--max-requests N]` | extract + load |
| `status [filters]` | units per endpoint × status, failed/deferred units with their last error |

Filters: `--year 2025` (repeatable), `--meeting-key 1276`,
`--session-key 9839`, `--endpoint laps` (repeatable), `--profile review`
(only `REVIEW_SESSION_KEY`, the Abu Dhabi 2025 race). The hidden option
`--now 2026-10-11T12:30:00Z` pretends a different time, to test the
live-window guard.

- `--dry-run` prints the planned units per race and makes no data requests. The metadata refresh still runs.
- Exit codes: `0` success (deferred units allowed), `1` failed units or an unexpected error, `2` config or database connection error, `130` interrupted.

### Review profile (for peer reviewers)

```bash
uv run src/cli.py run --profile review     # ~38 requests, ~1.5 min
uv run src/cli.py status --profile review
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < scripts/verify.sql
uv run src/cli.py run --profile review     # again: only the 8 metadata requests, nothing reloaded
```

### Live-window guard demo

`--force` makes the already completed review units get planned again:

```bash
uv run src/cli.py extract --profile review --force --now 2026-10-10T14:00:00Z
# → "API is live: live window of session 11384 (Qualifying)", 10 units deferred, exit 0
uv run src/cli.py extract --profile review   # picks the deferred units up again
```

## 6. Verification

[scripts/verify.sql](scripts/verify.sql) shows:
- row counts per table for the review race
- reconciliation of `meta.load_state` against the tables
- extract units by status, and the failed/deferred units
- sanity checks: drivers per race, grid coverage, `car_data` value ranges, duplicate laps

Tests:

```bash
uv run pytest -m "not db"   # unit tests, no network, no database
uv run pytest -m db         # integration tests against the compose Postgres (uses a throwaway f1_test database)
uv run ruff check . && uv run ruff format --check .
```

## 7. Expected runtimes and volumes

- ~85–90 races from 2023 to today. Each race takes ≈ 10 session-level requests + 20 `car_data` requests (one per driver).
- Full backfill ≈ 2,700 requests ≈ **1 h 45 min** at 25 requests/minute. The `--max-requests` option splits it into several runs.
- After a race weekend: ≈ 38 requests (~1.5 min), 8 of them the metadata refresh.
- `car_data` ≈ 33k rows per driver per race, ≈ 0.67 M rows per race, ≈ 55–60 M rows in total (several GB including indexes). Loading one race's `car_data` takes ~7 s. All other endpoints are small: `intervals` ≈ 26k rows per race, the rest below 2k.

## 8. Project plan / backlog

- [x] Ingest script for one race weekend, local PostgreSQL + Docker Compose
- [x] Stateful extract/load pipeline with raw zone, state tables and tests
- [ ] Lap-level aggregation of `car_data`
- [ ] First justified transformation (lap-grain fact table with tyre/weather/safety-car enrichment)
- [ ] Orchestrator calling the same functions (`refresh_metadata`, `extract`, `ingest.load`)
- [ ] Architecture v0.2, move to GCS + BigQuery

## 9. Repository structure

Based on the [Cookiecutter Data Science](https://cookiecutter-data-science.drivendata.org/)
layout. The pipeline modules sit directly in `src/`, without a package.

- `README.md`: this file
- `pyproject.toml`, `uv.lock`: project metadata and pinned dependencies (uv)
- `Dockerfile`, `docker-compose.yml`: pipeline image, local PostgreSQL, pgAdmin
- `.env.example`: all configuration keys, copy to `.env`
- `data/`: local data, gitignored
  - `raw/`: raw zone, `openf1/v1/<endpoint>/year=…/meeting_key=…/session_key=…/[driver_number=…/]data.json.gz` + `_manifest.json`
- `docs/`: `BRIEFING.md` (the task), `api-notes.md` (API findings), `architecture.md`, `decisions/` (ADRs)
- `scripts/`: `verify.sql` (verification queries)
- `sql/`: `001_meta.sql` (state tables), `002_raw.sql` (one typed table per endpoint)
- `src/`: pipeline modules
  - `cli.py`: command line (typer), a thin wrapper
  - `config.py`, `logging_setup.py`, `db.py`: settings from env, logging, connection + DDL
  - `client.py`: httpx + rate limiter + retries; `classify.py`: response → unit status
  - `endpoints.py`: endpoint registry; `discovery.py`: race selection, live-window guard
  - `raw_store.py`: raw zone paths, atomic writes, manifests
  - `state.py`: access to the `meta` tables
  - `fetch.py`: extract (planner + runner); `ingest.py`: load
- `tests/`: `unit/` (no network, no DB), `integration/` (marker `db`)

## 10. Known limitations

- No data can be fetched during live windows (30 min before to 30 min after any session). Runs then stop and defer the remaining work.
- A full backfill takes ~2 h because of the 30 requests/minute limit. Extraction is sequential on purpose (ADR 0005).
- OpenF1 is unofficial and partly undocumented, with no SLA. We verified the empty-result format (404 "No results found.") and the grid key ourselves. The blackout status (401 vs. 403) and `Retry-After` on 429 are unverified, see [docs/api-notes.md](docs/api-notes.md).
- The starting grid can omit pit-lane starters.
- `car_data.throttle` contains the value 104, outside the documented 0–100 range.
- `drivers.country_code` and `pit.pit_duration` are deprecated and will disappear after 2026. The columns stay nullable. New fields land in `_extra`.
- DRS status codes are not fully documented.
