# F1 Race Strategy & Overtaking Analytics - End-to-End Batch Pipeline

DENG HS26 - Florian Item & Florian Leimer

A batch pipeline that loads Formula 1 race data from the [OpenF1 API](https://openf1.org/docs/)
into PostgreSQL and answers one question for a race strategist: **how do tyre and pit
strategy and on-track position changes decide race outcomes?** Every driver's result is
split into the positions won or lost at the start, on track, in the pits and otherwise.
Kestra runs it every Monday after a race weekend.

**Contents**

1. [Quick start: run it on your laptop](#1-quick-start-run-it-on-your-laptop)
2. [Verify the result](#2-verify-the-result)
3. [Troubleshooting](#3-troubleshooting)
4. [Use case and user](#4-use-case-and-user)
5. [Data source](#5-data-source)
6. [Pipeline steps](#6-pipeline-steps)
7. [Data models (transformation)](#7-data-models-transformation)
8. [Orchestration, reruns and backfills](#8-orchestration-reruns-and-backfills)
9. [Architecture v0.2](#9-architecture-v02)
10. [Repository structure](#10-repository-structure)
11. [Limitations](#11-limitations)

---

## 1. Quick start: run it on your laptop

You only need **Docker Desktop** (or Docker Engine with Compose v2) and **git**. No
Python or anything else on your laptop: every step runs in a container.

| Before you start | |
|---|---|
| Free disk space | **at least 25 GB** for the full history (2023 until today): about 13 GB raw JSON + 7 GB database |
| Time of the first run | **about 2.5 hours** (about 1.5 min per race weekend, 92 race weekends as of October 2026). Later runs only fetch the new race (2 min). |
| Free ports | `8080` (Kestra) and `8085` (pgAdmin), see [Troubleshooting](#3-troubleshooting) |
| Docker Desktop | **started and running** for the whole time; keep the laptop awake during the first run |

All commands run **in the repository folder**. They are the same on macOS, Linux and
Windows PowerShell, unless a step says otherwise.

### Step 1: clone the repository

```sh
git clone https://github.com/FloHoliday/DENG.git
cd DENG
```

### Step 2: create your `.env`

```sh
cp .env.example .env
```

(Windows PowerShell: `Copy-Item .env.example .env`)

`.env` works as it is: nothing has to be changed. The passwords in `.env.example` work as they are. Change them if you like (the Kestra
password needs 8+ characters with an upper-case letter, a lower-case letter and a digit).
Never commit `.env`; git ignores it.

### Step 3: check the configuration

```sh
docker compose config --quiet
```

**Expected:** no output. An error like `required variable POSTGRES_PASSWORD is missing a
value` names the line in `.env` to fix.

### Step 4: build the pipeline image and start the services

```sh
docker compose build code
docker compose up -d --wait
```

The first command builds `deng-f1-code:local`, the image that contains the pipeline
scripts (Kestra starts every task from it). The second starts PostgreSQL, pgAdmin,
Kestra and Kestra's own database; Kestra loads the flow from `orchestration/flows/` by
itself. It takes 1-2 minutes.

**Expected:** the last lines all say `Healthy`, e.g.

```text
 ✔ Container deng-kestra-1          Healthy
```

### Step 5: run the pipeline in Kestra

1. Open **http://localhost:8080** and log in with `KESTRA_USER` / `KESTRA_PASSWORD` from
   your `.env` (default: `student@example.com` / `Change-me-Kestra1`).
2. Left menu **Flows** → click **`f1_race_weekend`** (namespace `deng.f1`).
3. Click **Execute** (top right). Keep the defaults (`since` = `2023-01-01`, `force` = off)
   and click **Execute** again.
4. Open the **Gantt** tab to see the five tasks and the **Logs** tab to follow progress.
   `fetch` is the long one: it prints one line per downloaded file.

**Expected:** after about 2.5 hours all five tasks are green and the execution state is
**SUCCESS**:

```text
check_source → fetch → load → transform → validate
```

> **In a hurry?** Execute with `since` = `2026-10-01` instead. That loads only the last
> two race weekends (about 5 minutes), enough to check that everything works. You can run
> the full history later; already downloaded races are skipped.

**If the first run is interrupted** (laptop asleep, Docker restarted, Wi-Fi gone): start
Docker again, run `docker compose up -d --wait`, open the failed execution in Kestra and
click **Restart**, or just execute the flow again. Nothing is downloaded or loaded twice.

From now on, Kestra runs the flow **every Monday at 06:00** (Zurich time) and loads the
race weekend of the past week, as long as Docker is running.

### Stop and start again

```sh
docker compose stop        # stop everything, keep all data
docker compose up -d --wait  # start again
docker compose down -v     # delete everything: database AND downloaded files (2.5 h to re-fetch)
```

---

## 2. Verify the result

### 2.1 Kestra

The execution of `f1_race_weekend` is **SUCCESS** and all five tasks are green. The
`validate` task's log ends with `13 of 13 checks passed`.

### 2.2 Run the checks yourself

```sh
docker compose run --rm code scripts/validate.py
```

**Expected output:**

```text
PASS  every fetched session (_SUCCESS) is loaded
PASS  raw laps: one row per (session, driver, lap)
PASS  raw stints: one row per (session, driver, stint)
PASS  raw pit: one row per (session, driver, lap)
PASS  every loaded race has a result and a starting grid
PASS  every loaded race is in core.fct_lap
PASS  telemetry is up to date for every loaded race
PASS  stint compound is a known value
PASS  tyre age is never negative
PASS  every lap is assigned to a stint (max 1 percent missing)
PASS  every served drive-through penalty is matched to a pit record
PASS  every loaded race is in mart_race_outcome
PASS  race outcome split adds up to positions gained
13 of 13 checks passed
```

The SQL checks are in [`sql/verify.sql`](sql/verify.sql); you can also paste that file
into pgAdmin.

### 2.3 Query the data

Open a SQL prompt (replace `f1` if you changed `POSTGRES_USER` / `POSTGRES_DB` in `.env`):

```sh
docker compose exec postgres psql -U f1 -d f1
```

Or use **pgAdmin** at **http://localhost:8085** (log in with `PGADMIN_DEFAULT_EMAIL` /
`PGADMIN_DEFAULT_PASSWORD`), then **Servers → Register → Server**: name `F1`, tab
*Connection*: host `postgres`, port `5432`, database/user/password from your `.env`.

The strategist table is in schema `marts`, which is the default: `SELECT * FROM
mart_race_outcome` works without a prefix. Raw tables must be named with their schema, e.g.
`raw.laps`.

**Reference race: 2026 Singapore Grand Prix** (`session_key = 11388`). These numbers are
the same on every machine:

```sql
SELECT 'laps' AS table_name, count(*) FROM raw.laps WHERE session_key = 11388
UNION ALL SELECT 'stints', count(*) FROM raw.stints WHERE session_key = 11388
UNION ALL SELECT 'pit', count(*) FROM raw.pit WHERE session_key = 11388
UNION ALL SELECT 'intervals', count(*) FROM raw.intervals WHERE session_key = 11388
UNION ALL SELECT 'car_data', count(*) FROM raw.car_data WHERE session_key = 11388;
```

| table_name | count |
|---|---|
| laps | 1240 |
| stints | 47 |
| pit | 25 |
| intervals | 28131 |
| car_data | 799898 |

Where were positions won and lost in Singapore? Sum of positions moved per cause, over
all classified finishers:

```sql
SELECT circuit_short_name, season,
       sum(abs(gained_lap1))     AS moved_lap1,
       sum(abs(gained_on_track)) AS moved_on_track,
       sum(abs(gained_in_pits))  AS moved_in_pits,
       sum(abs(gained_other))    AS moved_other
FROM mart_race_outcome
WHERE circuit_short_name = 'Singapore'
GROUP BY circuit_short_name, season;
```

| circuit_short_name | season | moved_lap1 | moved_on_track | moved_in_pits | moved_other |
|---|---|---|---|---|---|
| Singapore | 2026 | 22 | 40 | 11 | 10 |

With the full history loaded, the same query also returns rows for 2023-2025.

### 2.4 Look at the raw files

The raw JSON is stored in the Docker volume `deng_raw_data`, not in the repo folder (a
volume works the same on macOS, Linux and Windows). List or copy it with:

```sh
# list the files of 2026
docker compose run --rm --entrypoint ls code -R data/raw/2026
# copy everything into the folder raw-copy/ (rarely needed)
docker run --rm -v deng_raw_data:/from -v "$PWD/raw-copy:/to" deng-f1-code:local -c "import shutil; shutil.copytree('/from', '/to', dirs_exist_ok=True)"
```

---

## 3. Troubleshooting

| Problem | Cause and fix |
|---|---|
| `required variable POSTGRES_PASSWORD is missing a value` (or another variable) | `.env` is missing or incomplete. Run step 2 again and compare with `.env.example`. |
| `Bind for 127.0.0.1:8080 failed: port is already allocated` (or `8085`) | Another program or Docker stack uses the port, e.g. the course's Week 5 Kestra. Stop it (`docker ps` shows which container, then `docker stop <name>`), or set `KESTRA_PORT=8081` / `PGADMIN_PORT=8086` in `.env` and open that port instead. |
| `Cannot connect to the Docker daemon` / `docker: command not found` | Docker Desktop is not running. Start it and wait until it says *running*. |
| http://localhost:8080 does not load | Kestra needs about 30 s after starting. Check `docker compose ps`: `deng-kestra-1` must be `healthy`. If the containers are gone (Docker restarted), run `docker compose up -d --wait`. |
| Kestra login fails | Use exactly `KESTRA_USER` / `KESTRA_PASSWORD` from your `.env`. If you changed them after the first start, run `docker compose up -d --wait` again. |
| Flow `f1_race_weekend` is not listed in Kestra | Kestra syncs it from `orchestration/flows/` on start-up. Run `docker compose restart kestra`, wait until healthy, reload the page. The file name must start with `main_` (Kestra takes the tenant from it). |
| A task fails with `No such image: deng-f1-code:local` | Step 4 was skipped: run `docker compose build code`. |
| `check_source` fails with `OpenF1 access denied: Live F1 session in progress` | OpenF1 blocks everything while an F1 session is live. Kestra retries for about 2 h 45 min (15, 30, 60, 60 min); otherwise Restart the execution after the session has ended. |
| `fetch` fails with `N sessions failed, re-run to resume` | The API was overloaded or offline. Kestra already tried 4 times. Restart the execution later; finished sessions are skipped. |
| `validate` fails | A data check failed (the log says which). The data stays in the database for investigation. Please open an issue with the log. |
| `no space left on device` | The full history needs about 20 GB. Free disk space (or increase Docker Desktop's disk limit under *Settings → Resources*), then Restart the execution. |

---

## 4. Use case and user

**User / stakeholder:** an F1 team's race strategist (or a strategy-focused fan
analyst) who prepares the next race weekend and reviews the last one.

**Problem:** raw lap-by-lap and telemetry data is too granular and too large to reason
about directly. The strategist needs curated tables, filterable by **circuit** (what to
expect at the next race) and **season** (trends), that answer the question from the pitch:

> How do tyre and pit strategy and on-track position changes actually decide race outcomes?

**Data product:** `marts.mart_race_outcome`, one row per driver per race (see
[Data models](#7-data-models-transformation)), built on lap-, stint-, pit-stop- and
result-level fact tables in schema `core`. The core tables (one row per driver per lap,
stint, stop or race) also serve a possible ML use case.

## 5. Data source

- **Source:** [OpenF1 API](https://openf1.org/docs/), a free, unofficial, community-run
  REST API for Formula 1 data (not affiliated with the F1 companies). JSON over HTTP GET,
  no authentication for historical data (2023 season onward).
- **Live-session lock:** while any F1 session is live, OpenF1 denies **all** requests
  without a paid key (HTTP 401), including historical data. The pipeline therefore runs
  on Monday morning, and `check_source` fails early (and retries) if it is locked.
- **Sessions used:** only the **Race** session of each race weekend. Qualifying only
  enters through `starting_grid`; practice and sprint sessions are not used.
- **Endpoints used:** `meetings`, `sessions` (find the race and its `session_key`),
  `drivers`, `laps`, `stints`, `pit`, `position`, `intervals`, `race_control`, `weather`,
  `session_result`, `starting_grid` (fetched from the qualifying session) and `car_data`
  (telemetry, about 3.7 Hz per car, fetched per driver because a whole race at once is
  rejected with HTTP 422).
- **Not used:** `location` (very large, no clear use), `overtakes` (live only),
  `team_radio` (coverage dropped in 2026).
- **Volume:** most endpoints have tens to a few thousand rows per race; `intervals` about
  28,000; `car_data` about 800,000 rows (about 150 MB of JSON) per race.
- **Update behaviour:** a new race appears after each race weekend. Finished races were
  checked to be static: the 2026 Singapore race fetched 3 and 6 days after the race gave
  byte-identical files for all 32 endpoints/drivers.
- **Known data-quality issues** (handled in the staging views):
  - `throttle` goes up to 104 (about 10 % of samples), `brake` is 0/100/104.
  - `gap_to_leader` / `interval` are seconds or text like `+1 LAP`.
  - OpenF1 labels Sprints `session_type = 'Race'`; `session_name` is used instead.
  - `pit_duration` is deprecated (always equals `lane_duration`); `stop_duration` only
    exists from the 2024 US GP on.
  - one stint has no compound; 66 laps have no `lap_duration`.
  - `drs` is empty in 2026 (new regulations without DRS).

## 6. Pipeline steps

One flow, five tasks. Each task runs one script from [`scripts/`](scripts) in its own
container from the project image; the logic lives in [`src/`](src).

| # | Task | Script | What it does | Fails when | Retry |
|---|---|---|---|---|---|
| 1 | `check_source` | `check_source.py --since DATE` | Asks OpenF1 for finished race weekends since `DATE` and lists them | API down or locked by a live session | yes |
| 2 | `fetch` | `fetch.py --since DATE [--force]` | Downloads every endpoint of each Race into `data/raw/<year>/<meeting>/<session>/` (in the Docker volume `deng_raw_data`), unchanged JSON | any session incomplete | yes |
| 3 | `load` | `load.py` | Loads every complete session into typed tables in schema `raw` | wrong type, unknown field, row-count mismatch | no |
| 4 | `transform` | `transform.py [--full-refresh]` | Rebuilds the `staging`, `core` and `marts` models from [`sql/transform/`](sql/transform) | SQL error, duplicate key on a model's grain | no |
| 5 | `validate` | `validate.py` | Runs the checks in [`sql/verify.sql`](sql/verify.sql) plus raw-files-vs-database | any check fails | no |

Only the two network tasks retry (exponential, 5 min → 1 h, 4 attempts). The other three
fail for permanent reasons (bad data, bad SQL), where a retry would only repeat the
failure.

**Fail fast:** if `fetch` cannot complete every session, the run stops there and nothing
is loaded. A rerun skips everything that is already complete.

### 6.1 Fetch (ingestion)

- Throttled to 3 requests/second and 30/minute (`pyrate-limiter`), retried with
  exponential backoff on 422, 429, 5xx and timeouts (`tenacity`).
- A session folder gets a `_SUCCESS` marker (timestamp + row count per file) only after
  all its endpoints were downloaded. Files are written to a temporary name first and then
  renamed, so an interruption never leaves a half-written file.
- An empty response where data is expected counts as a failure (no `_SUCCESS`).
- A week without a race is not an error: `check_source` and `fetch` report "0 race
  weekends" and exit successfully; the later steps then have nothing new to do.

### 6.2 Load (storage)

- Schema-on-write: one table per endpoint in schema `raw` with one typed column per
  API field ([`sql/schema.sql`](sql/schema.sql)). A new, renamed or wrongly typed field
  fails the session's load instead of slipping through.
- **One transaction per session:** delete the session's rows, insert them again, compare
  every table's row count with `_SUCCESS`. On any error the session is rolled back and
  its earlier rows stay.
- **Incremental:** `raw.loaded_sessions` records which `_SUCCESS` marker each session
  was loaded from; only new or re-fetched sessions are loaded.

### 6.3 Transform and validate

See [Data models](#7-data-models-transformation). The transform runs all files in
`sql/transform/` in name order **in one transaction**: until it commits, queries see the
previous version of every model.

### 6.4 Running a step without Kestra

Every task can also be run by hand (handy for development):

```sh
docker compose run --rm code scripts/check_source.py --since 2026-10-01
docker compose run --rm code scripts/fetch.py --since 2026-10-01
docker compose run --rm code scripts/load.py
docker compose run --rm code scripts/transform.py
docker compose run --rm code scripts/validate.py
```

After changing Python code or SQL files, rebuild the image (`docker compose build code`)
so that Kestra and `docker compose run` use the new version.

## 7. Data models (transformation)

ELT: the data is loaded unchanged first, then transformed with SQL inside PostgreSQL.

```text
raw  (typed tables)  →  staging (views)  →  core (facts)  →  marts (for the strategist)
```

| Layer | Materialization | Why |
|---|---|---|
| `staging` | plain views | renaming, typing and cleaning only; no copy of the data |
| `core` | materialized views with a unique index on the grain; `fct_lap_telemetry` is an incremental table | the unique index makes a build with duplicate rows fail; telemetry is the only large input (about 0.8M rows per race) and is only recomputed for new or reloaded races |
| `marts` | materialized views with a unique index on the grain | small, pre-aggregated, fast to query |

Views and materialized views are dropped and rebuilt on every run, so a rerun always
gives the same result and a changed definition is picked up automatically.

### 7.1 Core models (schema `core`)

| Model | Grain | Content |
|---|---|---|
| `fct_neutralisation` | one Safety Car / VSC / red-flag period | start/end lap and time, from race control messages |
| `fct_lap` | (session, driver, lap) | lap time, compound, tyre age, pit in/out, neutralised, weather, fuel-corrected lap time, `is_clean_lap` |
| `fct_lap_position` | (session, driver, lap) | position at the end of each lap (order of crossing the line, unique per lap) |
| `fct_lap_telemetry` | (session, driver, lap) | top speed, slow-corner speed (10th percentile), % full throttle, braking events, lift-and-coast seconds |
| `fct_stint` | (session, driver, stint) | compound, length, clean laps, degradation (s/lap), grip loss (km/h/lap) |
| `fct_pit_stop` | (session, driver, in-lap) | lane time, stationary time, under neutralisation, red flag, penalty, `is_real_stop`, compounds before/after, pit loss |
| `fct_race_result` | (session, driver) | grid, finish, positions gained, number of stops, strategy (e.g. `M-H`) |
| `fct_position_swap` | (session, lap, gaining driver, losing driver) | every swap of two cars from one lap end to the next, with its cause: `on_track`, `pit` or `neutralised` |
| `fct_undercut_attempt` | (session, driver, lap) | car directly behind pits first, the car ahead pits 1-3 laps later; success if ahead afterwards |

**Cleaning rules (and why):**

- `is_clean_lap`: not lap 1, no pit in/out lap, no Safety Car/VSC/red flag, no rain, and
  faster than 107 % of the driver's median green lap. Only these laps show real tyre
  pace; the others are dominated by the start, pit lane, neutralisation or traffic.
- Fuel correction: `lap_duration - 0.03 s/kg * 100 kg * (total_laps - lap_number) / total_laps`,
  i.e. 0.03 s per kg of remaining fuel, 100 kg at the start, the same amount burned every
  lap. A car gets faster as fuel burns off, which would hide tyre degradation. Sources:
  [Michelin Simulation, "Showing our sensitive side" (2018)](https://simulation.michelin.com/canopy/technical-articles/showing-our-sensitive-side)
  (0.03 s per additional kg) and [TracingInsights](https://github.com/TracingInsights/2026)
  (same formula with 100 kg and linear burn).
- Fake pit stops: not every pit record is a stop. `is_red_flag` marks cars waiting in the
  pit lane during a red flag (20 to 40 min lane time), `is_penalty` a drive-through or
  stop-and-go, matched by race control's "PENALTY SERVED" message. Stop numbers, pit loss
  and undercuts only use `is_real_stop`. The stint data is not used for this: OpenF1 also
  starts a new stint after a penalty or red flag and misses some real stops.
- Degradation per stint = slope of fuel-corrected lap time over tyre age (clean laps
  only, at least 5), so every driver is only compared with themselves.

### 7.2 Mart (schema `marts`)

`mart_race_outcome`, grain (race, driver). It splits each driver's result,
`positions_gained = grid - finish`, into four parts that add up exactly (a validate check
fails the run otherwise); positive = positions won:

| Column | Positions won or lost ... | Built from |
|---|---|---|
| `gained_lap1` | at the start and on lap 1 (grid vs. position after lap 1) | `fct_race_result`, `fct_lap_position` |
| `gained_on_track` | by green-flag overtakes, made minus suffered | `fct_position_swap` (`on_track`) |
| `gained_in_pits` | by pit stops: own stops cost places, rivals' stops give places | `fct_position_swap` (`pit`) |
| `gained_other` | under Safety Car/VSC without a stop, when cars ahead retire, across laps missing in the source, and by penalties after the flag | `fct_position_swap` (`neutralised`), `fct_lap_position`, `fct_race_result` |

The split is filled for classified finishers with a grid position (DNF rows keep their
grid, strategy and stops, but no split). Next to it, what the driver did: `strategy`
(compound sequence, e.g. `S-M`), `n_stops` and `n_stops_under_neutralisation` (real stops
only), `green_pit_loss_s`, `avg_deg_s_per_lap`, `longest_stint`, `n_undercut_attempts`,
`n_undercut_successes`.

Example, "how was the Singapore 2026 result decided for the top 8?":

```sql
SELECT name_acronym, grid_position, finish_position, gained_lap1, gained_on_track,
       gained_in_pits, gained_other, strategy, n_stops
FROM mart_race_outcome
WHERE circuit_short_name = 'Singapore' AND season = 2026
ORDER BY finish_position
LIMIT 8;
```

## 8. Orchestration, reruns and backfills

Kestra ([`orchestration/flows/main_f1_race_weekend.yaml`](orchestration/flows/main_f1_race_weekend.yaml))
only schedules, orders, retries and shows the steps. **Idempotency lives in the scripts**,
so every way of running the flow again is safe:

| Situation | What to do | Why it is safe |
|---|---|---|
| Weekly run | nothing: schedule `0 6 * * 1` (Monday 06:00, Europe/Zurich), looks back 8 days from the scheduled date | the weekend's race is finished, and no session is live on Monday morning |
| A task failed | open the execution → **Restart** (continues at the failed task) | finished sessions are skipped, each session is replaced in one transaction |
| Missed Mondays (Docker was off) | **Triggers** tab → `monday_after_race_weekend` → **Backfill executions** with a date range | each backfill run uses its own scheduled date, not today |
| Full history or a specific period | **Execute** with `since` = e.g. `2023-01-01` | same flow, already loaded races are skipped |
| Re-download a race (suspected bad data) | **Execute** with `force` = on | new `_SUCCESS` marker → the session is reloaded |
| Two runs at once | they queue (`concurrency: limit 1`) | they never write the same files or rows at the same time |

Kestra watches `orchestration/flows/` (mounted to `/flows`, see
[`orchestration/application.yaml`](orchestration/application.yaml)): the flow is created on
start-up and updated within seconds whenever the file is saved. The file name must start
with `main_`, because Kestra 1.3 takes the tenant from the part before the first `_`.

## 9. Architecture v0.2

Changes since v0.1:
- The orchestrator is Kestra, not asset-based.
- The steps are separate tasks, with a source check before them and validation after.
- The transformation is plain SQL in PostgreSQL, not dbt.
- Telemetry is aggregated incrementally.

```mermaid
flowchart LR
    source["OpenF1 REST API<br/>Race sessions, JSON"]

    subgraph kestra["Kestra: weekly schedule, retries, restart, backfill, 1 run at a time"]
        direction LR
        check["1 check_source<br/>API reachable?<br/>new race weekends?"]
        fetch["2 fetch<br/>Python, rate-limited<br/>_SUCCESS per session"]
        load["3 load<br/>replace per session<br/>in 1 transaction"]
        transform["4 transform<br/>SQL: staging → core → marts"]
        validate["5 validate<br/>sql/verify.sql"]
        check --> fetch --> load --> transform --> validate
    end

    raw[("data/raw<br/>immutable JSON files<br/>volume deng_raw_data")]
    subgraph pg["PostgreSQL (Docker Compose)"]
        rawdb[("raw<br/>typed tables")]
        staging[("staging<br/>views")]
        core[("core<br/>facts, telemetry")]
        marts[("marts<br/>strategist tables")]
    end
    user["Strategist<br/>pgAdmin / SQL"]

    source --> check
    source --> fetch
    fetch --> raw --> load --> rawdb
    transform -.-> staging & core & marts
    marts --> user
```

**Runtime (Docker Compose, project `deng`, network `deng_default`):**

| Service | Purpose |
|---|---|
| `postgres` | project database (the F1 data) |
| `pgadmin` | browser UI for the database, http://localhost:8085 |
| `kestra` | orchestrator UI and scheduler, http://localhost:8080; starts each task as a container through the Docker socket |
| `kestra-postgres` | Kestra's own metadata (flows, executions, logs), separate from the F1 data |
| `code` | the pipeline image `deng-f1-code:local`, used for Kestra's tasks and for `docker compose run` |

`postgres`, `kestra-postgres` and `kestra` restart automatically with Docker
(`restart: unless-stopped`), so the Monday schedule survives a Docker restart.

**Final project (outlook):** the same steps load into BigQuery instead of PostgreSQL
(`--raw-dir gs://…` is already supported by the fetch and load steps), provisioned with
Terraform.

Security note: Kestra has access to the Docker socket so it can start task containers.
That is fine for a local single-user setup, but anyone who can edit flows can control
Docker. All ports are bound to `127.0.0.1`.

## 10. Repository structure

```text
├── README.md
├── docker-compose.yml        services (see Architecture)
├── Dockerfile                pipeline image deng-f1-code:local
├── .env.example              configuration template, copy to .env
├── pyproject.toml, uv.lock   Python dependencies (installed in the image with uv)
├── orchestration/
│   ├── application.yaml      Kestra server configuration (mounted into the kestra container)
│   └── flows/                Kestra flow main_f1_race_weekend.yaml
├── scripts/                  one entry point per pipeline step
├── src/                      fetch.py, load.py, transform.py, validate.py
├── sql/
│   ├── schema.sql            raw tables (load step)
│   ├── transform/            staging, core and mart models, run in name order
│   └── verify.sql            data checks (validate step)
```

The downloaded raw JSON is not in the repo folder: it lives in the Docker volume
`deng_raw_data` (see 2.4).

## 11. Limitations

- OpenF1 is unofficial, community-run, has no SLA and a 3 requests/second limit; it is
  completely unavailable during live F1 sessions.
- The fuel correction is a rule of thumb (0.03 s/kg, 100 kg, linear burn), not measured:
  the real fuel load and burn differ per car, circuit and fuel-saving, and the 2026 cars
  start with less fuel. Track evolution (the track getting faster during a race) is not
  corrected.
- SOFT/MEDIUM/HARD are relative per race (Pirelli picks three of its compounds); they are
  only comparable within one circuit and season. The 2026 regulation change means
  2023-2025 degradation does not transfer 1:1 to 2026.
- Laps are matched to Safety Car periods by the leader's lap number, and telemetry
  samples to laps by timestamp (from the start of one lap to the start of the next).
- Position changes are derived from lap-end positions: a car that passes and is passed
  back within the same lap is not counted, and a swap on a lap where one of the two cars
  pits counts as `pit`, even if it was a real overtake.
- A car that drives through the pit lane under Safety Car without changing tyres still
  counts as a real stop: OpenF1 has no tyre-change flag and its stint data is not
  reliable enough to detect it. Such stops are excluded from pit loss (neutralised), but
  not from stop counts.
- With one race per circuit and season, per-circuit conclusions rest on small samples;
  more seasons (2023-2025) make them more reliable.
- Materialized views are fully rebuilt on every run (simple and idempotent, cheap at
  this size); only telemetry is incremental.
