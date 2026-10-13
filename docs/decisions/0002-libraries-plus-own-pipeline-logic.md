# ADR 0002: Libraries for HTTP, retry and limiting; own pipeline logic

**Context.** We need rate limiting (two limits), retries with backoff,
storage, a CLI and Postgres bulk loading. We also have to explain every line
in the oral defence.

**Decision (approach B).**
- Proven libraries for the generic parts: `httpx` (HTTP), `tenacity` (retries), `pyrate-limiter` (3/s and 25/min), `fsspec` (storage), `psycopg` 3 (`COPY`), `typer` (CLI), `python-dotenv` (config).
- Our own small code for everything pipeline-specific: planning, unit state, classification, partition load.

**Alternatives.**
- (A) Fully hand-written: a sleep-based limiter and a retry loop (our first version). Easy to get subtly wrong (two limits, `Retry-After`), harder to test.
- (C) A framework such as dlt. It hides state, retries and schema handling. We tried it and dropped it as too opaque: we could not explain or control the state model.

**Consequences.** About 1,150 lines in `src/` (docstrings included), in 11
modules with one job each.
Library behaviour is pinned by `uv.lock`. There is no automated test suite
(we decided to drop it); `scripts/verify.sql` and the review race run are the
checks.
