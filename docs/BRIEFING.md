# Briefing for Claude Code: OpenF1 → local raw zone → PostgreSQL

> Hand this file to Claude Code as the task description (e.g. save as `docs/BRIEFING.md` and say "Implement the briefing in docs/BRIEFING.md, phase by phase").
> Version: 10 Oct 2026. Supersedes earlier plans that included Sprint sessions, `location`, an orchestrator and transformations.

---

## 0. Working agreement

- **This is a graded university project** (HSLU, Data Engineering HS26). Two students must be able to **explain, justify and debug every line** in an oral defence. Prefer simple, explicit, readable code over clever abstractions. Comments explain *why*, not *what*.
- Work **phase by phase** (§12). At the end of each phase: run the tests, summarise what was built, and list anything that deviated from this briefing.
- **Phase 0 is a verification spike.** Record the findings in `docs/api-notes.md`. If a finding contradicts an assumption in this briefing in a way that changes the design, stop and ask before building on it.
- Do **not** add dependencies beyond §4 without asking.
- Never commit secrets or data. Make small, meaningful commits, one logical change each.
- Be a good API citizen: never deliberately trigger rate limits or hammer the API while testing. Use mocked HTTP in tests.

---

## 1. Goal

Build a **failsafe, idempotent, manually triggered batch pipeline** that:

1. **Extracts** Formula 1 data for **Race sessions** from the public OpenF1 REST API into a **local raw zone** (files on disk), exactly as received.
2. **Loads** the raw files into a **local PostgreSQL** database.

Both steps are started by hand through a CLI. Later (not now) the raw zone moves to Google Cloud Storage and the warehouse to BigQuery, so keep the seams described in §13.

### In scope
- Sessions: `session_name = 'Race'` only, `is_cancelled = false`, seasons **2023 → today**.
- Session-level endpoints: `drivers`, `laps`, `stints`, `pit`, `position`, `race_control`, `session_result`, `weather`, `intervals`, `starting_grid`.
- Telemetry: **`car_data` only**, fetched per driver.
- Metadata (needed for discovery and the live-window guard): `meetings`, `sessions` (all session types).

### Out of scope (do not build)
- Sprint, qualifying or practice *data* (the qualifying `session_key` may only be used to fetch `starting_grid`, see §3).
- `location` and all other endpoints.
- Orchestrator / scheduler, transformations / dbt, data marts.
- GCS, BigQuery, Terraform.

---

## 2. Design principles (these are what the students will defend)

1. **Two decoupled stages.** Extract is the only code that calls the API. Load reads only from the raw zone. A rate-limit or outage can never corrupt the database, and reloading costs zero API calls.
2. **Raw zone = immutable record of what the API returned.** No parsing, cleaning or renaming before storage.
3. **Idempotency at a defined grain.**
   - Extract unit = `(endpoint, race_session_key, chunk_key)`.
   - Load partition = `(endpoint, race_session_key)`.
   - Running anything twice gives the same result.
4. **Failure is a recorded state, not a crash.** Every unit has a status in Postgres; a rerun continues where the last run stopped.
5. **Expected unavailability ≠ failure.** Live-session blackouts and not-yet-published data are `deferred`, not `failed`.
6. **Logic lives in a package; the CLI is a thin wrapper.** An orchestrator added later only calls the same functions.

---

## 3. API facts

### Verified
| Fact | Consequence |
|---|---|
| Base URL `https://api.openf1.org/v1`. Free tier: no auth, historical data from 2023. | No credentials needed. |
| Rate limit (free tier): **3 requests/second and 30 requests/minute**. | Limiter enforces both; configure **25/min** for headroom. |
| Data is "live" from **30 min before a session starts until 30 min after it ends**; live data requires a paid plan. | Live-window guard (§6.4); blackout responses → `deferred`. |
| `meetings` and `sessions` are refreshed daily at 00:00 UTC. | Refresh metadata at the start of every run. |
| Filter by any attribute via query string, e.g. `?session_key=9839&driver_number=44`; date comparisons like `date>=…` work. | Used for chunking. |
| The Sprint session has `session_type = 'Race'`. | **Select on `session_name = 'Race'`, never on `session_type`.** |
| Cancelled meetings exist (Imola 2023, `is_cancelled = true`). | Filter them out. |
| Polymorphic fields: `intervals.gap_to_leader` / `intervals.interval` can be a number or a string like `"+1 LAP"`; `session_result.duration` / `gap_to_leader` can be number, string (`"+1 LAP"`) or array (qualifying). | Store these as `text` in raw tables. |
| Deprecated, removed after the 2026 season: `drivers.country_code`, `pit.pit_duration`. | Treat as optional; never fail if missing. |
| Abu Dhabi 2025 race = `session_key 9839`. | Use as the review/test session. |

### Unverified → Phase 0 spike must check and document
1. **`starting_grid` key.** Observed: the Melbourne 2023 grid rows carry `session_key 7783`, which is that weekend's *Qualifying* session (race = 7787); the docs' example also queries the qualifying key. The students believe the race key works. **Test both** for race 9839 and its qualifying session in the same meeting: which returns rows, and which `session_key` the rows carry.
   - Implement whatever is confirmed. If unclear, implement: try race key → if empty, resolve the `Qualifying` session of the same `meeting_key` and query that. Store the key actually used in the manifest.
   - Note: a grid observed for a 20-car race had 18 rows (pit-lane starters likely missing). Document; don't treat as error.
2. **Empty result format:** `200 []` or `404` with a "no results" body? Test e.g. `laps?session_key=9839&driver_number=999`.
3. **`car_data` size for one driver × one race:** row count, response bytes, response time, any error (413/422/5xx/timeout). If problematic, chunk further by time window (§6.2).
4. **Blackout response code** (401 or 403?) — only observable during a live window (the Singapore GP race is Sun 11 Oct 2026). If not observed, handle both and record it as unverified.
5. Whether a `Retry-After` header is sent on 429 (read the docs/headers on normal responses; do not provoke a 429).

---

## 4. Tech stack

- Python **3.12**, project managed with **uv** (`pyproject.toml`, `uv.lock`), `src/` layout, package name `f1pipe`.
- `httpx` (HTTP client), `tenacity` (retries), `pyrate-limiter` (rate limiting — check the API of the installed major version, it changed between majors), `fsspec` (storage abstraction; local now, `gcsfs` later), `psycopg[binary]` 3 (Postgres, `COPY`), `typer` (CLI), `python-dotenv` or `pydantic-settings` (config — pick one, keep it simple).
- Dev: `pytest`, `respx` (mock httpx), `ruff`.
- PostgreSQL 16 via **Docker Compose** (Postgres only). The pipeline itself runs on the host with `uv run`.
- All timestamps stored as `timestamptz` in UTC.

---

## 5. Repository layout

```
.
├── README.md                    setup · run · verify · known limitations
├── docker-compose.yml           postgres:16 only, named volume, port from .env
├── .env.example                 all config keys, safe defaults, no secrets
├── .gitignore                   .env, data/, logs/, .venv/, __pycache__/
├── pyproject.toml  uv.lock
├── docs/
│   ├── BRIEFING.md              this file
│   ├── api-notes.md             Phase 0 findings
│   ├── architecture.md          diagram (mermaid) + data flow + grain
│   └── decisions/               short ADRs (one page each), see §11
├── sql/
│   ├── 001_meta.sql             meta schema (state, load_state, runs)
│   └── 002_raw.sql              raw schema (one table per endpoint)
├── scripts/
│   └── verify.sql               verification queries for README / reviewers
├── src/f1pipe/
│   ├── __init__.py
│   ├── config.py                settings from env
│   ├── logging_setup.py
│   ├── api/
│   │   ├── client.py            httpx + limiter + tenacity
│   │   └── classify.py          response → outcome/status
│   ├── endpoints.py             endpoint registry (§6.2)
│   ├── discovery.py             race selection, qualifying lookup, live windows
│   ├── storage/raw_store.py     paths, atomic write, manifest, read back
│   ├── state.py                 meta.extract_state / load_state / pipeline_run access
│   ├── extract.py               planner + runner
│   ├── load.py                  raw zone → Postgres
│   ├── db.py                    connection helper, apply DDL
│   └── cli.py                   typer app
└── tests/
    ├── unit/                    client, classify, discovery, raw_store, planner
    └── integration/             load idempotency against compose Postgres (marker: db)
```

---

## 6. Component specifications

### 6.1 Configuration (`.env.example`)
```
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=f1
POSTGRES_USER=f1
POSTGRES_PASSWORD=change-me
OPENF1_BASE_URL=https://api.openf1.org/v1
RAW_URI=file://./data/raw          # later: gs://<bucket>/raw
SCOPE_YEARS=2023,2024,2025,2026
RATE_LIMIT_PER_SECOND=3
RATE_LIMIT_PER_MINUTE=25
HTTP_TIMEOUT_SECONDS=60
MAX_RETRY_ATTEMPTS=6
SETTLING_DAYS=3
REVIEW_SESSION_KEY=9839            # Abu Dhabi 2025 race
LOG_LEVEL=INFO
```

### 6.2 Endpoint registry (`endpoints.py`)
A single declarative list; the rest of the code is generic over it.

| Endpoint | Query | Chunking | Notes |
|---|---|---|---|
| `meetings` | `year=Y` | per year | metadata, full refresh |
| `sessions` | `year=Y` | per year | metadata, full refresh, **all session types** (needed for live windows) |
| `drivers` | `session_key=S` | session | must complete before `car_data` is planned |
| `laps` | `session_key=S` | session | `segments_sector_*` arrays → `integer[]` |
| `stints` | `session_key=S` | session | |
| `pit` | `session_key=S` | session | `pit_duration` deprecated |
| `position` | `session_key=S` | session | |
| `race_control` | `session_key=S` | session | |
| `session_result` | `session_key=S` | session | may appear late → settling window |
| `weather` | `session_key=S` | session | |
| `intervals` | `session_key=S` | session | race-only endpoint |
| `starting_grid` | race key or qualifying key (Phase 0) | session | key used recorded in manifest |
| `car_data` | `session_key=S&driver_number=D` | **per driver** (`chunk_key = "driver=44"`) | optional sub-chunk by time window, `chunk_key = "driver=44/from=…"`, only if Phase 0 shows it's needed |

`chunk_key` for unchunked endpoints: `"all"`.

### 6.3 HTTP client (`api/client.py`)
- One `httpx.Client` per run with timeouts (connect 5 s, read `HTTP_TIMEOUT_SECONDS`) and a User-Agent naming the project. Keep `trust_env=True` (proxies).
- **Rate limiter** applied before *every* request (including retries), enforcing both 3/s and 25/min, process-wide. Extraction is **sequential** (one worker) — the rate limit is the bottleneck, so parallelism adds complexity without throughput. Document this as an ADR.
- **Retries with tenacity** for transient errors only: 429, 5xx, timeouts, connection errors. Wait = `Retry-After` seconds if present (capped, e.g. 120 s), else exponential backoff with jitter (base 2 s, max 60 s). Stop after `MAX_RETRY_ATTEMPTS`. Log every retry with reason and wait.
- Non-transient responses are returned to the caller for classification, not retried.
- Return a small result object: status code, parsed JSON (or None), raw bytes, URL, elapsed time, attempts.

### 6.4 Response classification (`api/classify.py`)
| Response | Unit status | Notes |
|---|---|---|
| 200 with ≥1 record | `done` | |
| empty (`[]` or the "no results" 404 from Phase 0), session ended **> SETTLING_DAYS** ago | `empty` | legitimate empty (e.g. no pit stops recorded) |
| empty, session ended **within** SETTLING_DAYS | `deferred` | data may still be published |
| 401 / 403 while a live window is active | `deferred` | blackout |
| 401 / 403 outside any live window | `failed` | unexpected → investigate |
| transient error after all retries | `failed` | `last_error` holds the reason |
| other 4xx | `failed` | no retry (bad request/bug) |
| 200 but body not valid JSON / not a list | `failed` | |

**Live-window guard** (`discovery.py`): using the loaded `raw.sessions` table (all session types), the API is "live" if `now ∈ [date_start − 30 min, date_end + 30 min]` for any session. Check before the run and before each unit. If live: stop extraction gracefully, mark remaining planned units `deferred`, log clearly, exit 0. Accept a hidden `--now` override for testing.

### 6.5 Discovery and planning (`discovery.py`, `extract.py`)
1. **Refresh metadata** for each year in scope: extract `meetings` and `sessions` to the raw zone and load them (full refresh per year). This is the only part fetched on every run.
2. **Eligible races:** `session_name = 'Race'`, `is_cancelled = false`, `date_end + 30 min < now`, year in scope, plus CLI filters (§6.9).
3. **Plan units** (upsert into `meta.extract_state` with status `pending`) for every session-level endpoint. Units already `done`/`empty` are left alone, **unless** the race ended within `SETTLING_DAYS` (re-planned every run) or `--force` is given.
4. **`car_data` units** are planned per race only after that race's `drivers` unit is `done`; the driver list is read from the `drivers` raw file. The runner handles this ordering in one run: session-level endpoints first (with `drivers` first), then plan and run `car_data` units.
5. Order of work: races oldest → newest, then endpoint order of the registry. `--max-requests N` stops cleanly after N API requests (useful to split a long backfill).

### 6.6 Raw zone (`storage/raw_store.py`)
Deterministic layout:
```
{RAW_URI}/openf1/v1/{endpoint}/year={YYYY}/meeting_key={M}/session_key={S}/[driver_number={D}/]data.json.gz
{RAW_URI}/openf1/v1/{endpoint}/…/_manifest.json
metadata: {RAW_URI}/openf1/v1/{meetings|sessions}/year={YYYY}/data.json.gz (+ _manifest.json)
```
- `session_key` in the path is always the **race** session key (also for `starting_grid`; the queried key goes in the manifest).
- Payload = the **exact response bytes**, gzip-compressed.
- Manifest (JSON): `endpoint`, `url`, `params`, `queried_session_key`, `race_session_key`, `http_status`, `record_count`, `sha256` (of the uncompressed payload), `bytes`, `fetched_at` (UTC ISO), `attempts`, `run_id`, `client_version`.
- **Atomic writes:** write to a temp file in the same directory, flush + fsync, then `os.replace()` to the final name. Write data first, manifest last — a manifest therefore always refers to a complete data file. Implement via fsspec so `gs://` works later (on GCS a single-object upload is already atomic; isolate the local temp+rename logic behind one function).
- Re-fetch overwrites the same path (idempotent). No deletes elsewhere.
- Empty results: write the payload and manifest too (`record_count: 0`) so "fetched and empty" is distinguishable from "never fetched".

### 6.7 State tables (`sql/001_meta.sql`)
```sql
CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta.pipeline_run (
  run_id        uuid PRIMARY KEY,
  command       text NOT NULL,
  params        jsonb NOT NULL,
  started_at    timestamptz NOT NULL DEFAULT now(),
  ended_at      timestamptz,
  outcome       text,              -- success | partial | failed | stopped_live_window
  counts        jsonb              -- per status
);

CREATE TABLE IF NOT EXISTS meta.extract_state (
  endpoint          text NOT NULL,
  race_session_key  integer NOT NULL,   -- for meetings/sessions: the year
  chunk_key         text NOT NULL,
  status            text NOT NULL CHECK (status IN ('pending','done','empty','deferred','failed')),
  attempts          integer NOT NULL DEFAULT 0,
  http_status       integer,
  last_error        text,
  record_count      integer,
  sha256            text,
  raw_path          text,
  last_run_id       uuid,
  first_planned_at  timestamptz NOT NULL DEFAULT now(),
  fetched_at        timestamptz,
  updated_at        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (endpoint, race_session_key, chunk_key)
);

CREATE TABLE IF NOT EXISTS meta.load_state (
  endpoint          text NOT NULL,
  race_session_key  integer NOT NULL,
  files_fingerprint text NOT NULL,      -- hash over sorted chunk sha256s
  row_count         integer NOT NULL,
  loaded_at         timestamptz NOT NULL DEFAULT now(),
  run_id            uuid NOT NULL,
  PRIMARY KEY (endpoint, race_session_key)
);
```
Tip for the metadata endpoints: either a separate key column or a clear convention (e.g. `race_session_key = year`); choose one, document it.

### 6.8 Raw tables and load (`sql/002_raw.sql`, `load.py`)
**One table per endpoint in schema `raw`**, columns named exactly like the API fields, plus lineage columns:
```
_race_session_key  integer      NOT NULL   -- load partition key (= planning key)
_raw_path          text         NOT NULL
_sha256            text         NOT NULL
_run_id            uuid         NOT NULL
_loaded_at         timestamptz  NOT NULL DEFAULT now()
_extra             jsonb                   -- unknown/unexpected fields, null if none
```
Field lists (from the OpenF1 docs; all nullable except the lineage columns):
- `meetings`: circuit_key, circuit_info_url, circuit_image, circuit_short_name, circuit_type, country_code, country_flag, country_key, country_name, date_end, date_start, gmt_offset, is_cancelled, location, meeting_key, meeting_name, meeting_official_name, year
- `sessions`: circuit_key, circuit_short_name, country_code, country_key, country_name, date_end, date_start, gmt_offset, is_cancelled, location, meeting_key, session_key, session_name, session_type, year
- `drivers`: broadcast_name, country_code, driver_number, first_name, full_name, headshot_url, last_name, meeting_key, name_acronym, session_key, team_colour, team_name
- `laps`: date_start, driver_number, duration_sector_1, duration_sector_2, duration_sector_3, i1_speed, i2_speed, is_pit_out_lap, lap_duration, lap_number, meeting_key, segments_sector_1/2/3 (`integer[]`), session_key, st_speed
- `stints`: compound, driver_number, lap_end, lap_start, meeting_key, session_key, stint_number, tyre_age_at_start
- `pit`: date, driver_number, lane_duration, lap_number, meeting_key, pit_duration, session_key, stop_duration
- `position`: date, driver_number, meeting_key, position, session_key
- `race_control`: category, date, driver_number, flag, lap_number, meeting_key, message, qualifying_phase, scope, sector, session_key
- `session_result`: dnf, dns, dsq, driver_number, duration (`text`), gap_to_leader (`text`), meeting_key, number_of_laps, position, session_key
- `weather`: air_temperature, date, humidity, meeting_key, pressure, rainfall, session_key, track_temperature, wind_direction, wind_speed
- `intervals`: date, driver_number, gap_to_leader (`text`), interval (`text`), meeting_key, session_key
- `starting_grid`: driver_number, lap_duration, meeting_key, position, session_key (as returned — may be the qualifying key)
- `car_data`: brake, date, driver_number, drs, meeting_key, n_gear, rpm, session_key, speed, throttle

Choose sensible Postgres types (`integer`, `numeric`/`double precision`, `boolean`, `timestamptz`, `text`). Reserved-word columns (e.g. `position`, `interval`) must be quoted consistently.

Indexes: `(_race_session_key)` on every raw table; additionally `(_race_session_key, driver_number, date)` on `car_data`.

**Load algorithm per `(endpoint, race_session_key)`**, eligible only when all of that partition's units are `done` or `empty`:
1. Compute `files_fingerprint`. If it equals `meta.load_state.files_fingerprint` and not `--force` → skip (no-op).
2. In **one transaction**:
   - `DELETE FROM raw.<endpoint> WHERE _race_session_key = :s`
   - read each chunk file from the raw zone, map known fields to columns, put unknown fields into `_extra` (log a warning once per endpoint/field), and `COPY` the rows in.
   - **Reconcile:** inserted rows must equal the sum of manifest `record_count`s, else raise → rollback.
   - upsert `meta.load_state`.
3. Commit. Log endpoint, session, rows, duration.

Metadata (`meetings`, `sessions`): same pattern, partition = year.

Why delete + COPY instead of row-level upsert: OpenF1 records have no guaranteed unique natural key (e.g. two `car_data` samples can share date and driver), so replacing the whole partition is simpler and provably idempotent. It also maps 1:1 to partition overwrite in BigQuery later. (Write this as an ADR.)

### 6.9 CLI (`cli.py`, entry point `f1`)
```
f1 init-db                                   apply sql/*.sql (idempotent)
f1 extract  [filters] [--force] [--max-requests N] [--dry-run]
f1 load     [filters] [--force]
f1 run      [filters] [--force] [--max-requests N]   = metadata refresh + extract + load
f1 status   [filters]                        counts per endpoint × status; list failed/deferred with last_error
f1 run --profile review                      only REVIEW_SESSION_KEY (fast, for peer reviewers)

filters: --year 2025 (repeatable) | --meeting-key 1276 | --session-key 9839 | --endpoint laps (repeatable)
hidden:  --now 2026-10-11T12:00:00Z  (testing the live-window guard)
```
- `--dry-run` prints planned units and the request count estimate, makes no data requests (metadata refresh allowed).
- Every command creates a `meta.pipeline_run` row.
- Exit codes: `0` success (deferred units allowed, but reported), `1` any `failed` unit or unhandled error, `2` config/DB connection error.
- Ctrl+C: finish nothing half-way — the current file write is atomic; mark the run `stopped`, leave remaining units `pending`.

### 6.10 Logging
Standard `logging`, one line per unit: `run_id endpoint race_session_key chunk_key status records attempts elapsed_ms`. Summary table at the end of each command. Optional file log under `logs/` (git-ignored).

---

## 7. Volume expectations (for README and sanity checks)

- ~85–90 races from 2023 to today. Per race ≈ 10 session-level requests + ~20 `car_data` requests ≈ **30 requests**.
- Full backfill ≈ 2,600–2,700 requests ≈ **~1 h 45 min** at 25/min. Normal "after a race weekend" run ≈ 30 requests (~1–2 min).
- `car_data` ≈ 25–30k rows per driver per race → ~0.5 M rows per race → **~45–50 M rows** total (several GB in Postgres incl. indexes). All other endpoints are small.
- Review profile (one race) ≈ 30 requests, a couple of minutes.

---

## 8. Tests

Unit (no network, `respx` mocks, no real sleeping — inject/patch the sleep/wait):
- client: 429 with `Retry-After` → waits that long and retries; 503 → backoff and retry; gives up after `MAX_RETRY_ATTEMPTS`; 400/404 not retried; limiter is invoked for every attempt.
- classify: every row of the table in §6.4, including the settling-window boundary.
- discovery: selects only `Race`, drops cancelled, drops races not yet ended + 30 min; live-window boundaries (exactly −30 min / +30 min).
- planner: idempotent planning (run twice → same units); `--force` resets; settling-window re-planning; `car_data` units only after `drivers` done.
- raw_store: deterministic paths; atomic write (simulate failure before rename → no final file, no manifest); manifest content; round-trip read.

Integration (marker `db`, needs `docker compose up -d`):
- load the same partition twice → identical row count, second run is a no-op (`load_state` unchanged).
- change a raw file → reload replaces the partition (no duplicates).
- reconciliation mismatch → rollback, table unchanged.

---

## 9. Verification (`scripts/verify.sql`, referenced in the README)
- Row counts per raw table per `_race_session_key` for the review session.
- Reconciliation: `meta.load_state.row_count` vs `count(*)` per partition.
- `meta.extract_state` summary by endpoint × status; list of `failed`/`deferred` with `last_error`.
- Sanity: drivers per race (18–22); `starting_grid` drivers missing vs `drivers`; `car_data` speed 0–400, throttle 0–100, `n_gear` 0–8; no duplicate `(driver_number, lap_number)` in `laps`.

---

## 10. Definition of done

1. Fresh clone → follow README: `cp .env.example .env`, `docker compose up -d`, `uv sync`, `uv run f1 init-db`, `uv run f1 run --profile review` → all endpoints for race 9839 are in Postgres; `scripts/verify.sql` shows consistent counts.
2. Running the same command again makes **no data API requests** for completed units (only the metadata refresh) and changes nothing in Postgres.
3. Interrupting `f1 run` mid-way (Ctrl+C) and rerunning completes the work with no partial files and no duplicate rows.
4. `--force` re-fetches and reloads with identical counts.
5. Live-window guard demonstrably works (`--now` inside a session window → graceful stop, units `deferred`, exit 0).
6. Tests green, `ruff check` clean.
7. No secrets or data in git; `.env.example` complete; README lists setup, commands, verification and known limitations.
8. `docs/api-notes.md` contains the Phase 0 findings; `docs/architecture.md` and the ADRs exist.

---

## 11. Documentation to produce
- `README.md`: purpose, architecture summary, prerequisites, setup, commands, review profile, verification, expected runtimes/volumes, known limitations, project structure.
- `docs/architecture.md`: mermaid diagram (API → client → raw zone → loader → Postgres; meta tables), grain of each step, failure handling.
- `docs/decisions/` ADRs (short: context, decision, alternatives, consequences):
  1. Separate extract and load via a raw zone
  2. Libraries for HTTP/retry/limiting, own pipeline logic (approach B; alternatives: fully raw, dlt)
  3. Unit-of-work grain and state table
  4. Partition replace (delete + COPY) instead of upsert
  5. Sequential extraction under a shared rate limit
  6. Race-only scope; `car_data` chunked per driver; `starting_grid` key decision (from Phase 0)
- Known limitations: no data during live windows; full backfill takes ~2 h; OpenF1 is unofficial and partly undocumented; starting grid may omit pit-lane starters; deprecated fields after 2026.

---

## 12. Phases

| Phase | Content | Done when |
|---|---|---|
| **0 Spike** | Verify §3 open points with a few manual requests; write `docs/api-notes.md` | Findings documented, design adjustments listed |
| **1 Skeleton** | uv project, ruff, pytest, `.env.example`, `.gitignore`, compose (Postgres), `config.py`, `db.py`, `sql/001_meta.sql`, `f1 init-db` | `f1 init-db` works against compose Postgres |
| **2 Client** | `api/client.py`, `api/classify.py` + unit tests | All client/classify tests green |
| **3 Raw zone** | `storage/raw_store.py` + tests | Atomicity and manifest tests green |
| **4 Discovery & extract** | metadata refresh, `discovery.py`, planner, runner, live-window guard, `f1 extract`, `f1 status` + tests | `f1 extract --profile review` fills the raw zone and state table correctly |
| **5 Load** | `sql/002_raw.sql`, `load.py`, `f1 load`, `f1 run` + integration tests | Review race loaded, reconciliation passes, reruns are no-ops |
| **6 Docs & verify** | README, verify.sql, architecture, ADRs; clean-clone dry run | Definition of done (§10) met |

---

## 13. Future seams (don't build now, just don't block them)
- **Orchestrator** (midterm requirement): will call the same package functions as the CLI (`refresh_metadata`, `plan`, `extract`, `load`). Keep them importable, parameterised and free of CLI-only code.
- **Docker image for the pipeline**: keep config purely env-based so the CLI can run in a container on the compose network.
- **Transformations** (dbt or SQL) will read from schema `raw`.
- **GCS:** `RAW_URI=gs://…` via `gcsfs`; extract must then write straight to GCS (no local staging in production).
- **BigQuery:** a second loader implementation with the same partition-replace semantics.