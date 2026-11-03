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
| Playwright journeys (production build, real API + worker, fixture harness) | 10 passed (11 after the header regression test was added) |
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
- **Fix (owner screenshot): on Instrument Detail, a long symbol overlapped the large price.** A width sweep
  (320–1600 px, 10 px steps) showed RELIANCE.NS and HINDUNILVR.NS running into the price at about 450–550 px and
  1040–1140 px. The symbol column was allowed to shrink below the unbreakable ticker (`min-w-0`). Now it never shrinks
  below the symbol; the price and actions wrap to the next line instead, the company name wraps (2 lines max), and the
  price block keeps its own width. After the fix the same sweep found no overlap or page overflow for RELIANCE.NS,
  HINDUNILVR.NS, BHARTIARTL.NS, ULTRACEMCO.NS, BRK-B, SMR, and ^NSEBANK. Screenshots inspected at 1440, 1100,
  1060, 500, and 390 px; the 1440 px layout is unchanged. New Playwright regression test (sweep 360–1400 px): it
  failed on the old code (overlap at 460–540 and 980–1040 px) and passes now.
  Files: `apps/web/src/features/instrument/InstrumentPage.tsx`, `tests/e2e/journeys.spec.ts`.
- Docs: `CLAUDE.md` (Grok optional, India + US, USD accounts in scope, streaming when entitled, fixed config
  names), `docs/UPGRADE_RULES.md`, this file, and `docs/STATUS.md` (new live URL).
- Checks after both fixes: Vitest 21 passed, Playwright journeys 10/10, tsc/ESLint clean; CI on `main` for commit
  357048e green.
- Data migrations: none. New environment variables: none. Unverified integrations: none added.

## Phase 1 — M00 Operational foundation (3 Nov 2026)
**Diagnosis of "Unexpected server error" at sign-in.**
- **Where the message comes from:** it is produced only by the API's catch-all 500 handlers (`apps/api/marketdesk/api/errors.py`). The frontend
  shows it verbatim; it never generates it. Non-JSON proxy errors show "Request failed (502)" and network failures
  "Cannot reach…". So the reported message was a real unhandled server exception.
- **Path traced:** `LoginPage` → `api.post` (`lib/api/client.ts`) → `POST /api/auth/login` → login rate-limit query
  (`login_attempts`) → argon2 verification → attempt record (DB write) → signed cookie → security/timing middleware
  → error handlers.
- **Production-like reproduction:**
  - **Setup:** production mode, synthetic owner credentials, isolated SQLite and PostgreSQL databases, served over
    HTTPS through a TLS-terminating proxy that adds `X-Forwarded-Proto/For` like Render's. The production Docker
    image was also run with its default command.
  - **Results:** no input produced a 500. Wrong password or username gives 401; malformed, non-JSON and
    lone-surrogate bodies give 422; correct credentials give 200. The cookie is HttpOnly, Secure, SameSite=Lax,
    Path=/ and 90 days. Missing CSRF or a foreign Origin gives 403. Logout revokes the session (the old cookie then
    gets 401), and the 6th failure gets 429.
  - **Hash variants:** fourteen malformed variants (quoted, `$$`-escaped, cut off, bcrypt, extreme memory, trailing
    whitespace) raise no exception.
- **What remains unknowable:** the exception behind the owner's earlier report is recorded only in Render's logs
  from that time, which this session cannot read, and request IDs did not exist then. The same service accepted the
  owner's credentials in checks on 3 Nov 2026.
  - **Documented 500-class candidate (fixed earlier):** missing migrations on the first deploy (DECISIONS #26).
  - **Silent misconfiguration found now:** a hash pasted with a trailing newline or space made the correct password
    fail as "incorrect".
- **Confirmed and fixed now:**
  - Pasted whitespace around `OWNER_USERNAME` and `OWNER_PASSWORD_HASH` is ignored.
  - Quoted, `$$`-escaped, cut-off, non-argon2 or memory-heavy hashes are refused at start-up with a specific
    message.
  - A trailing space in the typed username is ignored.

**Changes.**
- **Request IDs:** an `X-Request-ID` header goes on every response (a well-formed upstream ID is reused), error
  bodies carry `request_id`, and 500s show it as a reference.
- **Server logs:** sanitized log lines for failures and sign-in outcomes, never containing credentials, bodies or
  cookies.
- **Sign-in screen:** wrong credentials appear under the password field. Rate limits (with the wait time), an
  unavailable host or database, network failure and server errors (with the reference) appear as a separate notice
  with Try again. Typed input is kept.
- **Worker:** startup validation is role-specific, so a separate worker needs no owner credentials or session
  secret.
- **Status:** `/api/status` adds the database schema state. Settings shows schema, version and per-endpoint provider
  health. `/api/health` and `/api/readiness` already existed.
- **Backups:** database-agnostic logical backup/restore — `GET /api/backup/export` (owner only, no-store), a
  Settings "Full backup (JSON)" link, and `marketdesk export-data` / `import-data`. It works on Render Free without a
  shell.
- **Docs:** README Render reference (exact variable names, start command, automatic migrations, worker needs, how to
  read sign-in errors, backup/restore), `.env.example`, DECISIONS #35, and `docs/UPGRADE_PLAN.md` (phased roadmap).
- **Files:**
  - Backend: `apps/api/marketdesk/{api/app.py,api/errors.py,api/routes_system.py,config/__init__.py,cli.py,db/migrations.py,schemas/__init__.py,services/backup.py,worker/__main__.py}`
  - Frontend: `apps/web/src/{lib/api/client.ts,features/auth/LoginPage.tsx,features/auth/loginErrors.ts,app/App.tsx,features/settings/SettingsPage.tsx}`
  - Tests: `apps/api/tests/test_m00.py`, `apps/web/tests/loginErrors.test.ts`

**Checks.**
| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 17 | 107 passed, 1 skipped / 107 passed, 1 skipped (each skips the other database's backup test) |
| ruff, tsc, ESLint | clean |
| Vitest | 25 passed |
| Playwright journeys (fixture harness) | 11 passed |
| Production-like HTTPS proxy probe (SQLite and PostgreSQL) | all outcomes as listed above, no 500 |
| Browser sign-in at 1440×900 and 390×844 over HTTPS | wrong password → field error with inputs kept; 500 (intercepted response) → notice with reference, no password error; network failure (intercepted) → notice + Try again; Try again with the right password → signed in; reload keeps the session; logout → sign-in page and API 401. Screenshots inspected |
| Production Docker image (PostgreSQL, synthetic credentials) | quoted hash refused at start-up with the specific message; hash with trailing newline accepted; sign-in 401/200 with request IDs in logs; schema up to date; write 201; backup export 200 |

Data migrations: none (no schema change). New environment variables: none (optional `WORKER_*` already existed).

**Live verification on https://marketdesk-rhag.onrender.com after deploying ad45787 (3 Nov 2026, ~19:50 UTC).**
- `/api/health` and `/api/readiness` return 200 with `X-Request-ID`.
- An unauthenticated API call returns 401 with `request_id`, and the backup download refuses with 401.
- A wrong password returns 401 `invalid_credentials` with `request_id`.
- The owner's sign-in returns 200, with a cookie that is HttpOnly, Secure, SameSite=Lax and Path=/.
- Authenticated API calls return 200. The same cookie in a new client (a reload) is still signed in.
- Status: schema `0001` up to date, worker running, database round trip 2.1 ms.
- The backup download returns 200 with `no-store`: 11 tables, 86 rows, valid checksum. Only the counts were
  inspected; nothing was stored.
- Logout returns 204, and the old cookie then gets 401. Only this check's own session was signed out.
- The live sign-in page at 1440×900 (with the wrong-password state) and 390×844 renders without overflow;
  screenshots inspected.
- **Production sign-in therefore works on the deployed build.** The cause of the earlier 500 cannot be determined
  without Render's logs from that time. If it recurs, the reference shown on the sign-in screen matches a
  `request_id=` line in Render's logs.
- **Owner actions (optional):** none are required. Recommended: download a backup from Settings → Export and backup
  and keep it privately.

## Phase 2 — M01 India + US markets (3 Nov 2026)
**What changed.**
- **Canonical listing identity:**
  - `InstrumentRef` and the `instruments` table now carry the provider venue code, the ISO 10383 MIC and the
    country. Identity is marked verified only from quote/chart metadata, which carries the trading currency.
  - A new `instrument_identifiers` table holds provider/registry mappings: the Yahoo symbol now, room for SEC CIK and
    broker symbols later.
  - Venue codes map to identity in `providers/venues.py`, from Yahoo's own exchange codes and never from ticker
    text. Unknown venues stay unknown, and an index has a country but no MIC.
  - An ADR and its home listing (INFY vs INFY.NS) are separate instruments with their own currency, calendar and
    facts.
- **Search:**
  - `GET /api/market/search?region=all|IN|US`. Results carry exchange, MIC, country, type and whether the identity
    is verified.
  - The symbol picker has an All/India/US filter, and the picker and command palette show "NSE · IN · INR" style
    labels.
- **Watchlists:** an All/India/US/Other filter with counts, shown when a list mixes markets and remembered in this
  browser only. Existing lists and items are untouched.
- **Session states:**
  - `GET /api/market/sessions` returns open, closed (weekend, holiday, before open, after close; with next open) or
    unknown. It uses the published `exchange_calendars` 4.13.2 calendars: XNYS for NYSE/Nasdaq/Arca, XBOM for
    NSE/BSE, which share holidays.
  - DST comes from the calendar's timezone. Early closes are modelled.
  - Special sessions (2026-02-01 Budget, 2026-11-08 Muhurat) and dates outside the calendar's data (India: after
    2026-12-31) are "unknown", never guessed.
  - Shown in the market strip, the Instrument header and Settings.
- **Comparison:**
  - `GET /api/market/compare` takes 2–3 symbols. It keeps only dates on which every instrument has a close, rebases
    to 100 at the first common date, and reports how many dates each series lost.
  - Values are price returns in each instrument's own currency (Yahoo split-adjusted, dividends not included). Mixed
    currencies are flagged.
  - The Compare panel on Instrument Detail has a chart, a table alternative, add/remove controls and the
    plain-language method.
- **INR portfolio restriction:** kept explicit. A US listing shows "Trades in USD; the v1 portfolio is INR-only…"
  until M08.
- **Migration 0002:**
  - Additive: new nullable columns and a new table.
  - Backfill: a Yahoo identifier for every stored symbol; country/MIC only when the stored suffix or exchange name
    maps to exactly one venue, marked unverified.
- **Backups across the schema change:** restore builds the backup's schema revision in the empty target, loads the
  rows, then migrates to head, so pre-M01 backups restore into the new schema (`restore_with_migrations`).

**Holiday data check.** nseindia.com and bseindia.com could not be reached from this environment (HTTP 503), so the
India list was checked against broker-published lists:
- The library's 16 dates for 2026 match lists that include the 15 Jan Maharashtra municipal-election closure.
- Other lists show 15 and omit that date.
- The library list stops at 2026-12-31, after which India states are "unknown".

**Data migration evidence.**
- **Synthetic populated databases (SQLite and PostgreSQL 17):** every pre-existing column and every watchlist item
  are byte-identical after migrating.
- **A local populated copy:** 13 watchlist items survived. Identities were derived (unverified) and then verified
  from quotes.
- **Production rehearsal:** the production backup (92 rows, revision 0001) was restored into a scratch PostgreSQL
  database and migrated to 0002. Its owner-data fingerprint (watchlists and symbols, ledger totals, alerts, journal,
  settings) is identical to production's. The copy is deleted after the deploy check.

**Checks.**
| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 17 | 126 passed, 2 skipped / 127 passed, 1 skipped |
| `alembic check` (SQLite and PostgreSQL) and downgrade/upgrade 0002 on PostgreSQL | clean |
| ruff, tsc, ESLint | clean |
| Vitest | 28 passed |
| Playwright journeys (fixture harness) | 12 passed (new: compare; search→chart journey scoped to the price chart's range control) |
| Real-data browser journey (local server, Yahoo) | palette lists INFY (NYSE · US), INFY.NS (NSE · IN · INR), INFY.BO, INFY.BA; US filter shows only INFY; added INFY to a list → present after reload; watchlist filter All 11 / India 10 / US 1; INFY header "US session: Open · closes 16:00 GMT-5 · XNYS"; INFY vs INFY.NS vs SPY rebased with excluded-date counts and the currency warning; no page overflow at 1440/1024/390; screenshots inspected |

New dependency: `exchange-calendars==4.13.2` (pandas-based; Apache-2.0). No new environment variables.

**Live verification after deploying 301d223 (3 Nov 2026).**
- The schema migrated to `0002` and is up to date.
- The owner-data fingerprint is identical before and after the production migration: 2 watchlists with the same
  symbols, 2 alerts, ledger totals and settings.
- Sessions: India "closed (before the open)" with next open 03:45 UTC (09:15 IST); US "open" with close 21:00 UTC
  (16:00 New York, after the DST change).
- Search: `region=US` returns only INFY (NYSE); `region=IN` returns the NSE/BSE listings.
- Compare: INFY vs INFY.NS gives 239 common dates (13 and 8 excluded) and flags the different currencies.
- The owner's three listings (SMR, DOX, IFCI.NS) are now verified from quote metadata.
- The live instrument page at 1440 and 390 px has no overflow; screenshots inspected.
- The temporary copy of production data used for the rehearsal has been deleted.

**Known visual issue (pre-existing, not M01):** the price axis can label the area reserved for volume bars with
negative prices (e.g. "−4.00"). Fix candidate: move volume to its own chart pane (Lightweight Charts 5 panes).

## Known limitations carried forward
- Market status comes from published calendars (exchange_calendars); India data ends 2026-12-31 (later dates show "unknown") and special sessions are not modelled.
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
