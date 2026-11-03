# Status

_Last updated: 2026-11-03 — milestone 2 (frontend: all required screens)._

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

- Frontend (`apps/web`, React 19 + Vite 7 + Tailwind 4 + TanStack Query + RHF/Zod + Lightweight Charts 5):
  design tokens (dark + light), responsive shell (sidebar → icon rail → bottom nav), command palette (Ctrl/Cmd+K),
  shortcut help, Overview, Watchlists, Instrument Detail, Portfolio (ledger, holdings, allocation, CSV import/export),
  Alerts (worker status, sample replay), Journal, Settings (theme, density, data status, outage drill, backup, about).
- API types generated from OpenAPI: `cd apps/web && npm run gen:api` → `src/lib/api/schema.d.ts`.
- Manual screenshot pass at 1440/1024/390: no horizontal page overflow on any page.

## Next
- Vitest unit tests, Playwright journeys against the real API in fixture mode, screenshots in `docs/screenshots`.
- Dockerfile, compose, CI workflow, README, `.env.example`.
