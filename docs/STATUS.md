# Status

_Last updated: 2026-11-03 — milestone 1 (backend foundation)._

## Done
- Backend (`apps/api`): FastAPI app factory, settings with production safety checks, SQLite WAL + busy timeout,
  Alembic migration `0001`, all ORM models (settings, instruments, watchlists, ledger, imports, alerts/events,
  observations, journal, sessions, login attempts, market cache, worker status).
- Providers: `FixtureProvider` (committed deterministic dataset in `fixtures/market`, generator in
  `scripts/generate_fixtures.py`) and real `YahooProvider` (yfinance 1.7) behind one interface.
- Market service: memory + persisted bounded cache, TTLs, request de-duplication, bounded concurrency, timeouts,
  bounded retries with jitter, circuit breaker, explicit freshness statuses and stale fallback.
- Ledger engine (Decimal, average cost), portfolio service with full replay on every write, CSV preview/commit/export.
- Alerts with observation capture, sampled evaluation, unique event keys; worker process (`python -m marketdesk.worker`).
- Journal, rule-based briefing, preferences, fixture replay/outage controls, starter workspace, owner auth, public demo.
- CLI: `marketdesk migrate | hash-password | revoke-sessions | backup | restore | seed-demo | worker-health`.

## Checks run
- `cd apps/api && uv run pytest -q` → 64 passed.
- Yahoo via yfinance from this environment (2026-11-03): history + metadata and search worked for RELIANCE.NS and
  ITC.NS; `info` worked intermittently; the crumb endpoint answered HTTP 429 (non-fatal).

## Next
- Milestone 2: frontend (`apps/web`) — design tokens, shell, Overview, command palette, watchlists, instrument detail.
