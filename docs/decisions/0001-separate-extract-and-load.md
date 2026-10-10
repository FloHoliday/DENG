# ADR 0001: Separate extract and load via a raw zone

**Context.** OpenF1 is rate limited, sometimes unavailable (live windows) and
undocumented in places. If the database were written while requesting, every
API problem would become a database problem, and every reload would cost API
calls.

**Decision.** Two stages. Extract (`src/fetch.py`) is the only code that calls
the API, and it stores the exact response bytes plus a manifest in a raw zone
on disk. Load (`src/ingest.py`) reads only from the raw zone.

**Alternatives.**
- Load straight from the HTTP response: fewer moving parts, but reloads need the API again and outages leave half-written tables.
- Store parsed/cleaned data: smaller, but the original response would be lost, and parsing bugs could not be fixed afterwards.

**Consequences.** Reloading and schema changes cost zero API calls. The raw
zone is an audit trail: sha256 and record counts are checked at load time.
It needs disk space: ≈ 6 MB per race gzip-compressed (≈ 120 MB uncompressed), so ≈ 0.5 GB for all races. The raw zone moves to GCS
through fsspec without code changes in the stages.
