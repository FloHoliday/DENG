# ADR 0004: Partition replace (DELETE + COPY) instead of upsert

**Context.** OpenF1 records have no guaranteed unique natural key. For
example, two `car_data` samples can share `date` and `driver_number`, and
`race_control` messages can repeat. An upsert would need a key we cannot
trust.

**Decision.** Load replaces a whole partition `(endpoint, race_session_key)`
in one transaction:
1. `DELETE` the partition's rows.
2. `COPY` the rows from all its files.
3. Check that the inserted row count equals the sum of the manifests' `record_count`.
4. Update `meta.load_state`.

Any error rolls everything back, and the previous rows stay.

**Alternatives.**
- Row-level upsert on a guessed key: risks merging distinct rows or creating duplicates.
- Append only, with deduplication later: duplicates on every rerun, which makes the data harder to reason about.

**Consequences.**
- Provably idempotent: loading twice gives the same rows, and an unchanged fingerprint skips the load entirely.
- `COPY` is fast: ~670k `car_data` rows in ~7 s.
- Maps 1:1 to partition overwrite in BigQuery later.
- A partition is replaced as a whole even if only one driver file changed. That is acceptable at ~7 s per race.
