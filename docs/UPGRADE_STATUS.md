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
| Portfolio | INR and USD long-only accounts (DEPOSIT, WITHDRAWAL, BUY, SELL, DIVIDEND, confirmed SPLIT) plus explicit FX conversions; Decimal replay of both accounts on every edit; average cost, realized/unrealized P&L; all-accounts view in INR at a stated current rate (withheld when incomplete); CSV preview/import/export with formula-injection defence | No historical FX or consolidated returns; no broker CSV mapping presets |
| Alerts + worker | Price, crossing, completed-session volume/volatility and SEC filing rules; cooldown auto-rearm; quiet hours; unique event and delivery keys; unified inbox with scheduled morning/end-of-session briefings (exchange calendars); single worker every `ALERT_POLL_SECONDS` (300 s), started 45 s after the web server at nice 10 in single-container mode | No email/Telegram/push delivery; filing rules need `SEC_USER_AGENT` |
| Briefing | Rule-based: largest watchlist moves, distance to alert thresholds, recent alert events, journal reviews due | No Grok narrative (optional, M03/M05) |
| Journal | Thesis, risks, invalidation, decision, conviction, horizon, tags; immutable versions with change notes and evidence snapshots; then-vs-now comparison; review queue and history; plain-text rendering; filters | No Grok counterargument yet |
| AI research | Evidence-first cited answers (results, catalysts, compare, ask) on Groq's free tier (default) or xAI, with code-side checks, token/dollar and request caps, reuse, saved answers | No web search; Groq answers use one call without extra filing lookups |
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

## Phase 3 — M02 Company research workspace (3 Nov 2026)
**What changed.**
- **Instrument Detail tabs:** Overview (the existing panels), Financials, Filings and Events.
  - The tabs are a keyboard-operable tablist (arrow keys), and the selected tab lives in the URL (`?tab=`).
- **SEC EDGAR adapter (`providers/sec.py`, stdlib):**
  - Sources: `company_tickers.json` for ticker→CIK, `data.sec.gov` submissions, and XBRL company facts.
  - Sends nothing unless `SEC_USER_AGENT` (application name + contact email) is set, as SEC fair access requires.
    The SEC documentation and webmaster FAQ were read on 3 Nov 2026.
  - Rate limit: a process-wide budget (default 5 requests/s, capped at 9, under SEC's 10/s), with bounded retries
    and backoff on 429/5xx.
- **Normalization (`services/financials.py`, pure):**
  - Every value carries tag, unit, start/end, form, filing date, accession and a link to the filing index.
  - Balance-sheet values are instants; income and cash-flow values are durations.
  - Annual means 340–380 days and a standalone quarter 80–100 days; year-to-date values are excluded and Q4 is never
    derived.
  - The latest filing wins, with restatement provenance (marked "R").
  - One reporting currency per filer: no mixing, no conversion.
  - Templates: industrial; financial companies (SIC 6000–6499 leave revenue, gross profit and similar unmapped);
    IFRS filers.
- **Ratios:** computed in code with their formula and inputs: gross/operating/net margin, long-term debt to equity,
  ROE (ending equity, stated), P/E (latest annual diluted EPS, price date stated, same currency only) and free cash
  flow.
- **Scope:** US listings only. Indian listings get "SEC data does not apply". ADRs use their own US registrant's
  filings.
- **Caching:** submissions 6 h. Company facts are keyed by the latest periodic filing's accession, so a new 10-K/10-Q
  invalidates them and tab switches reuse the cache. A failed refresh shows the last good data marked stale, with
  the error.
- **Check tracking:** migration 0003 `research_checks` records last checked, last success, last error and latest
  filing, separately from the dates of the facts.
- **Refresh:** the worker re-checks watchlisted US companies once per `RESEARCH_REFRESH_HOURS` (default 24) and
  refetches facts only after a new periodic filing. It is isolated from alert evaluation.
- **Events:** confirmed events only — 8-K Item 2.02 results announcements, periodic reports, and Yahoo corporate
  actions. No estimated earnings dates are shown, because no verified source is configured.

**Not verified live (credential needed):**
- SEC requests require the owner's contact address in `SEC_USER_AGENT`. Until it is set, the production tabs show
  "not configured" (US) or "not applicable" (India).
- All SEC behaviour was tested with fictitious fixtures and a fake client. The tabs were visually checked with a
  local-only harness serving fixture data under a real ticker.

**Checks.**
| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 17 | 141 passed, 2 skipped / 142 passed, 1 skipped (normalizer 7, research service 8) |
| `alembic check` on PostgreSQL | clean (0003) |
| Vitest / Playwright | 28 passed / 13 passed (new: research tabs) |
| Visual (local harness, fixture SEC data) | Financials annual + quarterly, Filings, Events at 1440/1024/390; no page overflow; fixed doubled "××" on P/E, phone table width, wrapped filing dates |
| Production after deploying the backend (22e3e01) | schema 0003 up to date; owner data identical before/after (backup taken first, then deleted); research endpoints report "not configured"/"not applicable" |

New environment variables: `SEC_USER_AGENT` (required for SEC data, e.g. `MarketDesk you@example.com`),
`SEC_MAX_REQUESTS_PER_SECOND` (default 5), `RESEARCH_REFRESH_HOURS` (default 24). Data migration: 0003 (additive).

## Phase 4 — M05 Alerts, briefings and inbox (4 Nov 2026)
**What changed.**
- **Rule types** (`services/alert_rules.py` pure logic, `services/alerts.py` evaluation):
  - PRICE: at or above / at or below a level, on each new sampled quote (unchanged behaviour for existing alerts).
  - CROSS: fires only when two consecutive sampled observations lie on opposite sides of the level; the first
    observation after arming is a baseline.
  - VOLUME: a completed session's volume ≥ multiple × the average of the previous 5–60 completed sessions.
  - VOLATILITY: a completed session's |close-to-close return| ≥ multiple × the standard deviation of the previous
    5–60 daily returns.
  - FILING (US listings): one event per new SEC filing of the chosen forms (10-K, 10-Q, 8-K, 20-F, 6-K, DEF 14A), with
    a link to the document; the rule keeps watching. Needs `SEC_USER_AGENT`; until then it is skipped with a reason.
- **Completed sessions only:** the latest daily bar is dropped while the exchange calendar says that session is still
  trading or its state is unknown, so an unfinished day is never compared with full days.
- **Missing data:** stale, failed, missing or too-short data is never evaluated (never zero-filled); the reason is
  stored on the alert and shown under "Last evaluated".
- **Idempotency:** event keys are unique (`<alert>:<arm>` for price/session rules, `<alert>:filing:<accession>`);
  each event has one delivery row per channel (unique), so retries and worker restarts never duplicate an event or a
  notice. Event, deliveries and cooldown state are written in one transaction.
- **Cooldown:** optional automatic rearm 5 minutes to 7 days after firing (otherwise manual rearm, as before).
- **Quiet hours:** an HH:MM window in the display timezone (overnight windows and DST handled by `zoneinfo`). Events
  are still recorded; the in-app notice is held and released when the window ends. "Mark all read" cannot hide held
  notices.
- **Delivery channels:** only in-app exists. A channel failure is recorded per event (`failed` + error) and shown; no
  channel is ever shown as working without configuration.
- **Unified inbox** (`/api/inbox`, `/api/inbox/counts`, `/api/inbox/read`): alert events and stored briefings in one
  list with filters (type, market India/US, unread), explanations, timestamps, source links, delivery status and
  read state. The topbar bell shows the combined unread count.
- **Scheduled briefings** (`services/briefings.py`, run by the worker):
  - Morning: from 90 minutes before the open until the close of each trading day; end-of-session: 20 minutes after
    the close, once the session's daily bars exist (or after 6 hours with a coverage note).
  - Timing comes from the exchange calendars (XBOM for NSE/BSE, XNYS for US). Dates the calendar cannot describe
    (special sessions, India after 2026-12-31) get no briefing.
  - Stored once per (kind, market, session date). Content: session hours, largest completed-session moves among
    watchlisted symbols, volume ≥ 1.5× the 20-session average (stated as a figure, not a cause), triggered alerts,
    distance to price levels and due journal reviews, and a coverage note for symbols without data.
  - Not generated from the fixed sample dataset (its dates are historical). The fixture harness has a "Write sample
    briefing" test path instead.
- **UI:** the alert dialog offers all rule types, cooldown and quiet hours with inline validation. Alerts shows the
  rules (description, state including "Rearms in …", skip reasons) and the inbox.
- **Backup fix:** restoring a backup taken at an older schema revision no longer inserts columns that only later
  revisions have (found while rehearsing this migration on a copy of production data); regression-tested on SQLite
  and PostgreSQL.

**Data migration 0004 (additive).** New alert/event columns with defaults (existing alerts become PRICE rules with
manual rearm), nullable event prices (filing events have none), and tables `alert_deliveries` and `briefings`.
- Rehearsal on a copy of production (backup at 0003 restored into scratch PostgreSQL 17, migrated to 0004): the
  owner-data fingerprint (settings, instruments, watchlists and items, ledger, alerts, events, observations,
  journal) is identical; both alerts are PRICE rules.
- One worker cycle against that copy with Yahoo data evaluated nothing new (the markets were closed and the quotes
  already recorded) and wrote three briefings with correct calendar times: India morning 4 Nov (opens 09:15 IST),
  India and US end-of-session 3 Nov.

**Checks.**
| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 17 | 166 passed, 3 skipped / 168 passed, 1 skipped (M05: 27, incl. crossing edges, incomplete sessions, DST quiet hours, cooldown, held/failed deliveries, filing dedupe, calendar timing, briefing idempotency, pre-M05 backup restore) |
| Migration 0004 up/down/up and `alembic check` (SQLite and PostgreSQL) | clean |
| ruff, tsc, ESLint | clean |
| Vitest | 30 passed |
| Playwright journeys (fixture harness) | 14 passed (alert journey now: crossing rule → one inbox event → mark read persists; new: sample briefing in inbox and bell, filters) |
| Visual (fixture harness) | Alerts page and dialog at 1440/1024/390, no page overflow; fixed cramped condition column, long cooldown label, raw ISO times in explanations |

No new environment variables. External channels (email/Telegram/push) are not built; nothing claims to send them.

**Live verification after deploying 3daf7de (4 Nov 2026).**
- CI: web, API on SQLite and PostgreSQL, migrations-match-models and Docker jobs passed; the browser-journeys job
  failed at its "OpenAPI types are in sync" step because the committed TypeScript types predated the fixture briefing
  endpoint (the journeys themselves passed locally). The regenerated types shipped with the M08 commit.
- The schema migrated to `0004` and is up to date; the owner-data fingerprint (instruments, watchlists and items,
  ledger, alerts, events, journal) is identical before and after. Both existing alerts are PRICE rules, still armed.
- The first worker cycle after the deploy wrote three briefings from Yahoo data: India morning 4 Nov (opens 09:15
  IST), and India and US end-of-session 3 Nov (moves versus the previous close, a volume note, next-session times).
- Inbox, counts and alert endpoints return 200; the bell shows "Inbox: 3 unread". The Alerts page and the new alert
  dialog render at 1440 and 390 px with no page overflow and no console errors (read-only check; nothing written).
- The pre-deploy backup and the scratch rehearsal database have been deleted.

## Phase 5 — M08 USD portfolios and FX (4 Nov 2026)
**What changed.**
- **Accounts:** INR and USD, keyed by the existing `currency` column of each transaction (every existing row was INR
  and is unchanged). Each account is replayed separately with its own cash, holdings, P&L and fees.
- **US listings:** buys, sells, dividends and splits of USD instruments are recorded in the USD account; recording an
  instrument in the other currency's account is refused with the account to use. Indices and FX series cannot be held.
- **FX conversions** (new transaction type `FX`): one row with two legs — amount + fees leave the paying account, the
  amount received arrives in the other. It records the quoted USD/INR rate (INR per USD, optional; must agree with the
  amounts within 2%), the rate's source (required) and time. The effective rate is shown. Conversions are transfers:
  they are not deposits, withdrawals or gains.
- **Replay across accounts:** every create, edit, delete and import replays both accounts, so a conversion that would
  overdraw INR, a USD purchase dated before its funding, or deleting a conversion that funded later purchases is
  rejected with the offending row.
- **All accounts view** (`/api/portfolio/overview`): each account's native value, a display-only INR conversion at the
  current valuation rate (Yahoo `USDINR=X`; a synthetic `SX:USDINR` series in the fixture harness) with pair, source,
  market time and status, and a total only when every account is fully priced and every rate is usable; otherwise the
  reasons are listed and only a labelled partial figure is shown. No historical FX, so no consolidated profit or return.
- **CSV:** `currency` selects the account (INR or USD); FX rows use `counter_currency`, `counter_amount`, `fx_rate`,
  `fx_source`, `fx_time`. Old files (without the new columns) still import; non-FX fingerprints are unchanged, so
  duplicate detection of existing rows is unaffected. Holdings export per account.
- **UI:** an account switcher on Portfolio (INR / USD / All accounts, in the URL), currency-correct figures throughout,
  a "Convert currency" action and FX fields in the transaction dialog, FX rows in the ledger shown from either side.

**Data migration 0005 (additive).** Adds nullable FX columns and admits `FX` in the type check; existing rows are not
rewritten.
- Tests: a 0004 backup with the CLAUDE.md acceptance ledger restores, migrates and reads back identically (summary and
  every transaction); fingerprints of non-FX rows equal the pre-M08 formula.
- Rehearsal on a copy of production (backup at 0004 restored into scratch PostgreSQL 17, migrated to 0005): owner-data
  fingerprint identical.

**Not built in this phase:** broker-specific CSV mapping presets (roadmap item 45 asks for source mapping); the
canonical format covers both accounts and FX rows. Historical FX (needed for consolidated returns) is out of scope by
design.

**Checks.**
| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 17 | 180 passed, 3 skipped / 182 passed, 1 skipped (M08: 14, incl. FX legs, rate convention and consistency, cross-account replay on create/edit/delete, overview with and without a rate, CSV round trip, migration preservation) |
| Migration 0005 on a populated SQLite database | existing row byte-identical; type check enforced; down/up clean |
| Migration 0005 up/down/up and `alembic check` (SQLite and PostgreSQL) | clean |
| ruff, tsc, ESLint / Vitest | clean / 30 passed |
| Playwright journeys (fixture harness) | 15 passed (new: FX conversion funds a USD purchase; all-accounts view with the stated rate) |
| Visual (fixture harness) | Portfolio USD and All accounts at 1440/1024/390 and the FX dialog; no page overflow |

Fixture data: a synthetic `SX:USDINR` series was added by the generator with its own seed; every existing series is
byte-identical. No new environment variables.

**Live verification after deploying da3c882 (4 Nov 2026).**
- CI on 48c406b: all five jobs green (API on SQLite and PostgreSQL, migrations match models, web, Docker, and the
  browser journeys including the OpenAPI types check). The M08 run on da3c882 was superseded by it.
- The schema migrated to `0005` and is up to date; the owner-data fingerprint is identical before and after
  (the production ledger has no transactions yet, so nothing else changed).
- `/api/portfolio/summary` (INR and USD), `/api/portfolio/overview` and the USD transaction filter return 200.
- The Yahoo valuation rate `USDINR=X` resolves (94.64 INR per USD, quoted in INR, status available) when queried
  from this environment; the live overview requests it only once a USD account has transactions.
- The live Portfolio page renders at 1440 and 390 px with no overflow or console errors; "Convert currency" opens the
  FX form (read-only check, cancelled). Follow-up: the account switcher is now shown even on an empty ledger.
- The pre-deploy backup and the scratch rehearsal database have been deleted.

## Live SEC verification (4 Nov 2026, after the owner set `SEC_USER_AGENT`)
- Settings status reports SEC enabled. The worker had already refreshed the watchlisted US companies.
- SMR (NuScale Power, CIK 1822966): profile, 40 filings with links, 30 events (latest: 8-K Item 2.02 results,
  5 Aug 2026), annual and quarterly statements (12 lines). Quarterly ratios are extreme but correct: the 10-Q filed
  5 Aug 2026 reports Q2 revenue of $75,000 against a $64.0M operating loss (margin −853×); each input links to that
  filing.
- DOX (Amdocs, a 20-F/6-K filer, fiscal year to 30 Sep): profile, filings and events work. Its statements end at
  FY2024 because SEC's company-facts data (checked directly) contains nothing filed after 2024, even though the FY2025
  20-F was filed 15 Dec 2025. **Fix:** the Financials tab now states when the latest periodic report has no figures in
  SEC's company-facts data yet, naming that filing and the filing the shown figures come from.
- IFCI.NS: every research dataset reports "SEC data does not apply" (not a US registrant).
- Also fixed (an M08 leftover seen in the live check): Instrument Detail still said the portfolio was INR-only and
  disabled "Add transaction" for USD listings; it now opens the dialog on the USD account (indices and exchange rates
  stay non-holdable). The browser journey that asserted the old message now checks the new behaviour.
- Browser check after deploying 295406a: DOX Financials shows the notice above FY2020–FY2024 statements; SMR shows
  none; the INR-only header text is gone; no page overflow at 390 px; no console errors (read-only check).

## Phase 6 — M10 Decision journal (4 Nov 2026)
**What changed.**
- **Structured thesis:** decision (WATCH/BUY/ADD/HOLD/TRIM/SELL/AVOID, labelled "your decision"), conviction 1–5 and
  horizon, alongside the existing thesis, risks, invalidation, tags and review date.
- **Immutable versions:** `journal_versions` holds each version's content and evidence; rows are never updated. An edit
  that changes any thesis field (title, date, thesis, risks, invalidation, decision, conviction, horizon) requires a
  change note and creates the next version; tags and the review date change in place. A note's instrument cannot
  change. Concurrent edits racing for the same version number get a 409.
- **Evidence snapshots:** at create, each new version and each review: quote (value, currency, market time, session,
  status), fundamentals (P/E, market cap, dividend yield, P/B with status), and up to five recent SEC filings for US
  listings (status recorded when not applicable or not configured). Capture failures are recorded, never block saving.
- **Compare** (`GET /api/journal/{id}/compare?version=N`): the stored snapshot beside today's data, fetched and not
  stored; price change in the instrument's currency (dividends not included), filings since, and splits since the
  snapshot (which withhold the price change).
- **Reviews:** `GET /api/journal?due=true` is the queue; `POST /api/journal/{id}/reviews` records outcome
  (intact/weakened/invalidated/closed), notes, the reviewed version, the date it was due, evidence and the next review
  date (must be after today), and moves the queue.
- **UI:** review queue on Journal; cards show your decision, conviction, horizon and version; a History / Evidence /
  Reviews view with a line diff between any two versions (removed and added lines marked in text, not only colour).
- **Form controls fix:** an explicit width (`w-40`, …) on Input/Select/Textarea now wins over the default full width
  (the class helper does not merge conflicting utilities); the Journal filters and the new version pickers sit inline.
  The Portfolio "Transactions" header wraps its filters on phones.
- **Not built:** the cited Grok counterargument (roadmap item 54) waits for M03 and `XAI_API_KEY`.

**Data migration 0006 (additive).** New entry columns (version defaults to 1) and tables `journal_versions` and
`journal_reviews`. Each existing note gets version 1 with its current text, marked "recorded before versioning" with no
evidence (none was captured at the time); entry rows are not rewritten (tested).
- Rehearsal on a copy of production (backup at 0005 into scratch PostgreSQL 17, migrated to 0006): owner-data
  fingerprint identical. Production has no journal notes yet.

**Checks.**
| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 17 | 187 passed, 3 skipped / 189 passed, 1 skipped (M10: 6 — version-one evidence, explicit edits and immutability across a market move, compare incl. split withholding, review queue/history/validation, field validation, migration backfill) |
| Migration 0006 up/down/up and `alembic check` (SQLite and PostgreSQL) | clean |
| ruff, tsc, ESLint / Vitest | clean / 32 passed (new: line diff) |
| Playwright journeys (fixture harness) | 15 passed (journal journey now: edit refused without a change note → v2 → diff → evidence then/now → review recorded) |
| Visual (fixture harness) | Journal with review queue, History diff, Evidence, Reviews at 1440 and 390; Portfolio filters at 390; no page overflow |

No new environment variables.

**Live verification after deploying b43bdc1 (4 Nov 2026).**
- CI: all jobs green, including the browser journeys and the OpenAPI types check.
- The schema migrated to `0006` and is up to date; the owner-data fingerprint is identical; the new tables are empty
  (production had no journal notes).
- `/api/journal`, the review queue (`?due=true`) and a missing note (404) respond correctly. The live Journal page and
  its new-note form (decision, conviction, horizon) render at 1440 and 390 px with no overflow or console errors
  (read-only check; no note was written to the live journal).
- Real-data evidence capture was exercised on a local Yahoo-mode copy instead: a RELIANCE.NS note stored an INR price,
  and an SMR note stored a USD price with its market time and Yahoo fundamentals (no P/E: earnings are negative).
- The pre-deploy backup and the scratch rehearsal database have been deleted.

## M03 — Cited Grok analyst (moved forward; 4 Nov 2026)
The owner added an xAI key as `GROK_API` (Render) and asked for the most capable assistant that fits free credits.

**Design for limited credit ("evidence first, one call").**
- MarketDesk retrieves and computes the evidence in code: quote; one-year price statistics (1m/3m/1y change, high,
  low, max drawdown); fundamentals; for US registrants SEC annual and quarterly statements with period changes and
  ratios, the filing list, and the latest results release (8-K Item 2.02 exhibit 99). Each item is a source `S1..Sn`
  with as-of date, fetch time and status. Comparisons get an aligned latest-fiscal-year table (period ends checked).
- One structured Responses API call (`text.format` json_schema, strict) answers from that package. The model may call
  one read-only tool, `read_filing`, for at most `AI_MAX_TOOL_CALLS` filings that are already in the filing list
  (sec.gov archive URLs built from CIK + accession; nothing else can be fetched).
- Answers are checked in code: unknown source ids are removed and flagged, facts without sources flagged, figures in
  facts/calculations matched against the cited sources (rounding and units tolerated), advice-like wording flagged.
- Budget: `AI_DAILY_BUDGET_USD` (default $0.50) and `AI_DAILY_REQUESTS` (30) per UTC day; a worst-case estimate is
  reserved before dispatch under a lock (plus a PostgreSQL advisory lock), then reconciled with xAI's reported
  `cost_in_usd_ticks`. Interrupted jobs count their reservation as spent. Reuse: the same request on unchanged
  filings/statements/trading day returns the saved answer at no cost.
- Model `grok-4.3` by default ($1.25/$2.50 per M tokens, docs.x.ai/docs/models, 4 Nov 2026); `XAI_MODEL=grok-4.7` for
  the strongest model at ~2.4× the price. If xAI rejects an optional setting, the request is retried once without it.
- Jobs run in a background thread and the UI polls progress; at most two run at once.
- Only public data and the question are sent; never the portfolio or journal. No web/X search. The key is read from
  `GROK_API` (or `XAI_API_KEY`), never logged or returned; `GROK_ENABLED=false` turns AI off.

**UI.** "Ask Grok" on Instrument Detail: Latest results / Catalysts / Compare (up to two more listings) / Ask; progress
steps; the answer labelled as model output with fact/calculation/interpretation and certainty badges, `[S1]` citations,
flagged checks, uncertainties and gaps, the source list (as-of, fetched, status, link), data cutoff, tokens and cost;
saved answers per listing. Settings shows status, model, today's spend and the limits.

**Data migration 0007 (additive):** table `ai_answers`.

**Not built:** the journal counterargument (M10 item 54) and Grok narratives on briefings; web/X search tools.

**Checks.**
| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 17 | all passed (M03: 17 with a fake xAI client — disabled without a key, validation flags, reuse, budget and request caps, concurrent reservations, stale-job recovery, failures incl. 429/malformed/incomplete/schema mismatch, compare, results release + model-requested filing via the tool loop, figure tolerance, key never in errors or responses, option fallback) |
| Migration 0007 up/down/up and `alembic check` (SQLite and PostgreSQL) | clean |
| ruff, tsc, ESLint / Vitest | clean / 32 passed |
| Playwright journeys (fixture harness + local fake xAI endpoint) | 16 passed (new: Ask Grok → cited answer → sources → repeat request reuses the saved answer → Settings shows usage) |
| Visual | research panel at 1440 and 390, Settings section; no page overflow; budget line and saved list refresh when a job finishes |

**Live check after deploying a24ca3c (4 Nov 2026).**
- Migration 0007 applied; Settings reports Grok on (`grok-4.3`, $0.50 and 30 answers per day).
- One "Latest results" request for SMR collected 7 sources in code (quote, price history, fundamentals, annual and
  quarterly SEC statements, filing list, and the 8-K Item 2.02 results release), then xAI answered
  **HTTP 400 "Incorrect API key provided"**: the key stored in Render as `GROK_API` is not accepted by xAI. No answer
  was produced and xAI does not bill rejected requests.
- That check found three bugs, fixed in the follow-up commit: the 400 key error was treated as a generic bad request
  (and retried once without optional settings) instead of a key error; a failed request was charged its whole
  worst-case reservation ($0.13 of the $0.50 day) instead of the usage xAI reported (zero); and late in the day a
  request whose worst case did not fit was refused instead of being answered in one call without extra lookups. The
  final usage of a successful answer was also not saved when it was updated in place. The miscounted failed record was
  deleted from the live database (budget back to $0). Settings now shows a non-secret description of the configured
  key (whether it starts with `xai-` and its length) to diagnose a wrong key, and surrounding quotes are ignored.
- After deploying 3b6d2cb the live status reports the stored key "does not start with 'xai-', 56 characters". xAI keys
  start with `xai-`; a 56-character key matches the format of a Groq (groq.com) key, a different provider. Waiting for
  the owner: an xAI API key from console.x.ai, or a decision to support Groq's free tier as the AI provider.

**Docs fix:** the M08 README edit had removed the Alerts, Tests, Layout, Runtime versions and Attribution sections (and
the M10 journal section was therefore never inserted). All are restored from history, and the journal and Grok sections
added.

## M03 follow-up — Groq free tier as the provider (4 Nov 2026)
The owner's key turned out to be a Groq key and the owner chose Groq's free tier.
- **Verified docs (console.groq.com, 4 Nov 2026):** chat completions at `https://api.groq.com/openai/v1`; strict
  json_schema output on `openai/gpt-oss-120b`, `gpt-oss-20b`, `qwen/qwen3.8-27b`; structured output cannot be combined
  with tool use; `reasoning_effort` and `include_reasoning`; listed base limits for gpt-oss-120b 30 requests/min,
  1,000/day, 8,000 tokens/min, 200,000 tokens/day; 429 with `retry-after`; `x-ratelimit-*` headers.
- **Implementation:** provider chosen from the key prefix; Groq client (stdlib) with quota headers captured; one strict
  structured call per answer (`openai/gpt-oss-120b`, reasoning low, reasoning text omitted, 2,300 completion tokens);
  evidence trimmed in fixed steps until the request fits 7,300 tokens (source ids unchanged; trims listed on the
  answer); daily token allowance 150,000 and 30 answers, reserved before the call and counted from reported usage;
  a 429 waits once if `retry-after` ≤ 20 s; rejected optional settings are dropped once (json_object fallback).
- **UI:** "Ask AI" (provider-neutral); answers name the model and provider; Settings shows provider, key shape,
  today's tokens and the provider's remaining requests.
- **Tests:** 9 Groq tests (provider choice, request shape, token allowance, truncated output, 429/413, option
  fallbacks, trimming with stable ids, HTTP client and quota headers); browser journeys now run the Groq path against
  the local fake endpoint.

**Live verification on Groq after deploying 2e07c08 (4 Nov 2026).**
- Status reports provider Groq (free tier), model `openai/gpt-oss-120b`, a `gsk_` key, 150,000 tokens and 30 answers per
  day.
- The first live answer (results, SMR) completed in one call with S4 (SEC statements) and S7 (results release) cited,
  $0 cost; six of its seven flags were checker errors (signs, Unicode dashes, dates, unit-written figures), fixed in
  5ba8753 with a regression test built from that answer. Repeating the same request returned the saved answer at no
  cost, as designed.
- A fresh question on SMR after the fix: revenue, gross profit and operating-loss figures all matched the cited
  statements, no flags; 5,296 input + 464 output tokens (53 reasoning), $0, within the 7,300-token request limit.
  About 5–7k tokens per answer, so the 150,000-token allowance covers the 30 answers a day.
- CI: the browser journey for the USD account was flaky (two "Transaction recorded." toasts on screen at once); the
  journey now dismisses the first one. All 16 journeys pass locally.

## Known limitations carried forward
- Market status comes from published calendars (exchange_calendars); India data ends 2026-12-31 (later dates show "unknown") and special sessions are not modelled.
- Render Free sleeps after 15 minutes idle; alerts are only evaluated while it is awake.
- Yahoo (yfinance) is unofficial; it refuses `quoteSummary` from Render, so some fundamentals are derived and labeled.
- Portfolio has INR and USD accounts; there are no returns metrics (XIRR/TWR) and no historical FX by design.

## Next concrete action
Phase 7 — **M06 Screener + peers** (see `docs/UPGRADE_PLAN.md`). Owner input still open: Alpaca key/secret + feed (M04). M03 runs on Groq's free tier; an `xai-` key would switch it to xAI.
