# Upgrade status

_Baseline audit: 3 Nov 2026, `main` after commit f19e3cd (roadmap upload). Rules: `docs/UPGRADE_RULES.md`.
Roadmap: `docs/MARKETDESK_ROADMAP.txt`. Older history and decisions: `docs/STATUS.md`, `docs/DECISIONS.md`._

## Deployment (checked 3 Nov 2026)
- Live: https://marketdesk-rhag.onrender.com (Render Free, Docker, `python -m marketdesk.serve`). The old URL
  (`marketdesk-9vmi`) now answers with Render's `x-render-routing: no-server` 404.
- `/api/health` 200, `/api/readiness` 200, owner sign-in 200, provider Yahoo, worker running.
- Storage: Neon PostgreSQL (AWS ap-southeast-1 pooler) via `DATABASE_URL`. The new service sits in the same region:
  database round trip **1.3 ms** (the old service: 175 ms). Server time for settings/watchlists ≈ 13–17 ms.
- The roadmap's "Unexpected server error during login" was the first deploy's missing-migration 500, fixed by the
  self-migrating startup (DECISIONS #26). Sign-in on the live service works.

## Capability map (what exists today)
| Area | Implemented | Not implemented / roadmap gap |
| --- | --- | --- |
| Frontend routes | `/` Overview, `/watchlists`, `/instrument/:symbol`, `/portfolio`, `/alerts`, `/journal`, `/settings`, 404; login screen; Ctrl/Cmd+K palette; shortcut help; dark/light; responsive shell (sidebar → rail → bottom nav) | No onboarding flow; no dedicated status page (Settings → Data status serves that role) |
| API routes | `/api/health`, `/api/readiness`, `/api/status`, `/api/auth/{login,logout,session}`, `/api/settings`, `/api/briefing`, `/api/workspace/starter-watchlist`, `/api/market/{search,snapshots,benchmarks,history,fundamentals,actions}`, `/api/watchlists…` (CRUD, items, order, membership), `/api/portfolio/{summary,transactions…,import/preview,import/{token}/commit,export/*.csv}`, `/api/alerts…` (+ rearm), `/api/alert-events…` (+ read), `/api/journal…`; `/api/fixture/*` only in fixture mode | No request IDs on errors/logs |
| Auth | Single owner: `OWNER_USERNAME` + argon2 `OWNER_PASSWORD_HASH`; HMAC-signed cookie (`SESSION_SECRET`), 90-day sliding; CSRF token + Origin check; login rate limit; sign-out revocation, `revoke-sessions` epoch (applies within 15 s); dev bypass only in development; production refuses missing secrets | — |
| Database | SQLAlchemy 2.1 + Alembic, one revision `0001_initial_schema`; 15 tables (settings, instruments, watchlists/items, ledger, import batches, alerts/events, quote observations, journal/tags, login attempts, market cache, worker status, unused legacy `auth_sessions`); SQLite WAL or PostgreSQL; `ensure_migrated` at startup under a file lock | PostgreSQL backup/restore is provider-side only (no app-level verified restore) |
| Market data | `MarketDataProvider` protocol (search, quote, history, fundamentals, corporate actions, validate); `YahooProvider` (yfinance 1.7; derived fundamentals when Yahoo refuses `quoteSummary`); `FixtureProvider` (test harness, refused in production); `MarketDataService` (memory + persisted cache, TTLs, de-duplication, retries, per-endpoint circuit breakers, stale fallback) | No SEC EDGAR, no streaming/Alpaca, no exchange calendars (market status is always "unavailable") |
| India + US | Any Yahoo symbol can be searched, charted and watchlisted in its native currency (USD shown as $); bare NSE/BSE names get a `.NS`/`.BO` suggestion | No region/currency filters, security-type/symbol-mapping validation, or comparison chart |
| Portfolio | INR long-only ledger (DEPOSIT, WITHDRAWAL, BUY, SELL, DIVIDEND, confirmed SPLIT), Decimal replay on every edit, average cost, realized/unrealized P&L, CSV preview/import/export with formula-injection defence; non-INR instruments refused with an explanation | No USD accounts or FX events (M08) |
| Alerts + worker | Price ABOVE/BELOW alerts, fire once then rearm, unique observation/event keys, single worker every `ALERT_POLL_SECONDS` (300 s); in single-container mode the worker starts 45 s after the web server, at nice 10; in-app inbox | No volume/volatility/filing alerts, quiet hours, or external delivery |
| Briefing | Rule-based: largest watchlist moves, distance to alert thresholds, recent alert events, journal reviews due | No Grok narrative (optional, M03/M05) |
| Journal | Thesis, risks, invalidation, tags, review date; plain-text rendering; filters | No versioning/snapshots (M10) |
| Settings/diagnostics | Theme, density, default watchlist, timezone, data status (provider health, storage, DB round trip, created-at, worker), backup guidance, attribution; `Server-Timing` header on `/api` responses | — |
| AI | None. No xAI/Grok code or keys | M03 |

## Commands (verified in this repository)
Setup and local run (Python 3.13 + uv 0.11, Node 22):
```bash
cd apps/api && uv sync && uv run marketdesk migrate
```
```bash
cd apps/api && DEV_AUTH_BYPASS=true uv run uvicorn marketdesk.main:app --reload --port 8000
```
```bash
cd apps/api && DEV_AUTH_BYPASS=true ALERT_POLL_SECONDS=60 uv run python -m marketdesk.worker
```
```bash
cd apps/web && npm ci && npm run dev
```
Tests and checks:
```bash
cd apps/api && uv run ruff check marketdesk tests && uv run ruff format --check marketdesk tests && uv run pytest
```
```bash
cd apps/api && TEST_DATABASE_URL=postgresql://USER:PW@HOST:PORT/SCRATCH_DB uv run pytest
```
(The PostgreSQL run drops and recreates the `public` schema of that database: never point it at production.)
```bash
cd apps/web && npx tsc -b --noEmit && npx eslint . && npx vitest run && npm run build
```
```bash
cd tests/e2e && npm ci && npx playwright test journeys.spec.ts
```
(Builds nothing itself: run `npm run build` in `apps/web` first. Add `DATABASE_URL=postgresql://…/SCRATCH_DB` to run
the journeys on PostgreSQL.)
```bash
docker build -t marketdesk:local .
```
Operations (inside the container or `apps/api`): `python -m marketdesk.cli {migrate,hash-password,revoke-sessions,worker-health,backup,restore}`.
`backup`/`restore` work on SQLite only. For the production PostgreSQL database, take a backup before any schema change:
```bash
pg_dump --format=custom --file=marketdesk-$(date +%F).dump "$DATABASE_URL"
```
and test the migration on a copy (a Neon branch, or `pg_restore --no-owner --dbname "$SCRATCH_URL" FILE`, then
`DATABASE_URL=$SCRATCH_URL uv run alembic upgrade head`).

## Baseline results (3 Nov 2026, this environment)
| Check | Result |
| --- | --- |
| ruff check / format | clean |
| pytest (SQLite) | 94 passed |
| pytest (PostgreSQL 17, scratch DB) | 93 passed, 1 skipped (SQLite-only backup test) |
| tsc + ESLint | clean |
| Vitest | 21 passed |
| Playwright journeys (production build, real API + worker, fixture harness) | 10 passed |
| Live service | health/readiness/sign-in 200; worker running; DB round trip 1.3 ms |

## Changes in this session
- **Fix (owner report): long names made the chart header overlap.** With RELIANCE.NS selected, the Overview chart
  header clipped the change percentage at 1280 px and 768 px, ran the date range under the chart selector, and hid
  the price on phones. The chart legend also ran under the price axis on narrow screens. Fix: `Panel` gained
  `wrapHeader` (title keeps its width, the meta line wraps below, actions move to their own line when needed),
  used by `ChartPanel`. The Overview shows the price on phones too. The chart legend is bounded to the plot width via
  `timeScale().width()`/`subscribeSizeChange` (lightweight-charts 5.2 API, checked in the installed typings).
  Screenshots inspected at 1440, 1280, 1024, 768, and 390 px (Overview, Instrument, Watchlists, palette): no
  clipping or overlap, and no page overflow.
  Files: `apps/web/src/components/ui/Panel.tsx`, `apps/web/src/features/market/ChartPanel.tsx`,
  `apps/web/src/features/market/PriceChart.tsx`, `apps/web/src/features/overview/OverviewPage.tsx`.
- **Fix found while verifying on the live site: the Overview watchlist panel clipped content.** The live check at
  1280 px (the owner's "Harsh Stocks" list) showed the panel title cut to "Watchl…" and the star buttons partly
  outside the panel; the compact table was 29 px wider than the panel. Fix: the compact instrument column is fluid
  (`w-full max-w-0`, truncates), panel titles keep priority over the meta text, and between 1280 and 1399 px the
  Overview uses a 7/5 chart/watchlist split, so full symbols fit (8/4 from 1400 px, i.e. the 1440 layout is
  unchanged). Measured: no table or page overflow at 1280, 1366, 1400, 1440, 1600, 1024, or 390 px. Screenshots
  inspected. Files: `apps/web/src/features/watchlists/WatchlistTable.tsx`, `apps/web/src/components/ui/Panel.tsx`,
  `apps/web/src/features/overview/OverviewPage.tsx`.
- Docs: `CLAUDE.md` (Grok optional, India + US, USD accounts in scope, streaming when entitled, fixed config
  names), `docs/UPGRADE_RULES.md`, this file, and `docs/STATUS.md` (new live URL).
- Checks after both fixes: Vitest 21 passed, Playwright journeys 10/10, tsc/ESLint clean; CI on `main` for commit
  357048e green.
- Data migrations: none. New environment variables: none. Unverified integrations: none added.

## Known limitations carried forward
- Market open/closed status is always "unavailable" (no verified exchange calendar).
- Render Free sleeps after 15 minutes idle; alerts are only evaluated while it is awake.
- Yahoo (yfinance) is unofficial; it refuses `quoteSummary` from Render, so some fundamentals are derived and labeled.
- Portfolio is INR-only; there are no returns metrics (XIRR/TWR) by design.

## Next concrete action
The owner selects a milestone. The roadmap recommends **M00 — Operational foundation** first. Much of it already
exists; the remaining work is checklisted below. Nothing in it has been started.

### M00 implementation checklist (proposed)
- [ ] **01 Login states.** Keep 401/429/503 messages, and add distinct messages for network failure and for the
      HTML/502 a waking Render instance returns ("server is starting, retrying…" with a retry). Add a request ID
      (`X-Request-ID`) to every response, error body, and log line, without secrets.
- [ ] **02 Status screen.** Extend Settings → Data status (or add `/status`): app version, migration revision
      (current vs head), per-endpoint provider breakers (prices/fundamentals/search), worker last error and
      heartbeat age. Sanitized: no hostnames beyond what is shown now, no secrets.
- [ ] **03 Backup/restore + migration check.** An app-level PostgreSQL backup (`pg_dump` in the image, or a
      versioned JSON export of owner tables). Restore into a separate scratch database, verified by row counts and
      checksums in a pytest that runs in the `api-postgres` CI job. A documented `alembic upgrade` dry run on a copy.
- [ ] **04 Connection/freshness banner.** A global "server unreachable / offline" banner with a working Retry that
      refetches queries; confirm every panel's ErrorState offers retry and keeps stale data visible.
- [ ] **05 Onboarding.** A first-run checklist on Overview (watchlist or NSE starter → first transaction or CSV
      import → first alert), stored in `app_settings` (no schema change), plus an integrations list showing only
      integrations that exist (Yahoo now).
- [ ] Tests: request-ID and sanitized-error pytest; backup → restore round trip on PostgreSQL; Playwright for the
      offline banner and onboarding; screenshots at 1440/1024/390.
- [ ] Data safety: no schema migration expected; if one becomes necessary, take a `pg_dump` (or Neon branch) first
      and test the migration on the copy.
