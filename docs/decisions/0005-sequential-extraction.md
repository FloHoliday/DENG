# ADR 0005: Sequential extraction under a shared rate limit

**Context.** The free API allows 3 requests/second and 30 requests/minute.
Responses take 0.05–2.5 s. The per-minute limit, not latency, sets the speed.

**Decision.** One worker. A single limiter (3/s and 25/min, leaving headroom)
is acquired before every request, retries included. Units run in a fixed
order: races oldest first, `drivers` first, then registry order, then
`car_data`.

**Alternatives.** Thread pool or async with a shared limiter. Throughput
would be the same (25/min), but the code would be more complex: concurrent
state writes, ordering of `drivers` before `car_data`, and harder log reading
and debugging.

**Consequences.**
- Simple, deterministic and easy to follow in the logs.
- A full backfill takes ~1 h 45 min. `--max-requests` splits it into several runs.
- If a paid plan with higher limits is used later, this decision should be revisited.
