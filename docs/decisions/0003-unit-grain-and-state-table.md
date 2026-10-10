# ADR 0003: Unit-of-work grain and state table

**Context.** A full backfill is ~2,700 requests and takes almost 2 hours. It
will be interrupted (rate limits, live windows, Ctrl+C), and a rerun must
neither repeat finished work nor skip unfinished work.

**Decision.** One extract unit = one API request = `(endpoint,
race_session_key, chunk_key)`. Its status (`pending`, `done`, `empty`,
`deferred`, `failed`) is stored in `meta.extract_state` and committed right
after the unit finishes. Loading works on partitions `(endpoint,
race_session_key)`, tracked in `meta.load_state` with a fingerprint over the
sha256 of the partition's files. Every command is recorded in
`meta.pipeline_run`. For `meetings`/`sessions`, `race_session_key` holds the
year.

**Alternatives.**
- Marker files per session (our first version, `_SUCCESS`): coarse. One failed endpoint meant re-checking the whole session, and the reasons for failure were not queryable.
- State per race only: simpler, but one failed driver would block 30 requests.

**Consequences.**
- Reruns are cheap and precise.
- `status` and `verify.sql` answer "what is missing and why" with SQL.
- `deferred` (expected: live window, settling) is kept apart from `failed` (needs investigation).
- The database is needed during extract too.
