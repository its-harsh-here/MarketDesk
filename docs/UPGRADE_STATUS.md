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

## Capability map (updated at the final release check, 5 Nov 2026)
| Area | Implemented | Not implemented / gap |
| --- | --- | --- |
| Pages | Overview, Watchlists, Screener, Macro, Portfolio (holdings, ledger, performance, rebalance, stress), Alerts + inbox, Journal, Lab, Settings, Instrument (overview, financials, filings, events, earnings, valuation, peers, compare), login; palette, shortcuts, workspaces, dark/light, responsive shell | No onboarding wizard (Settings → Data status covers status) |
| Data | Yahoo (yfinance) with cache, de-duplication, retries, per-endpoint circuits, stale fallback; SEC EDGAR (submissions, company facts, filings); exchange calendars (NSE/BSE, NYSE/Nasdaq); fixture provider for tests only | Streaming covers US listings only (IEX, single exchange, via Alpaca); Indian prices are polled; official macro statistics (FRED key / Indian source) |
| Portfolio | INR and USD long-only accounts, FX conversions, Decimal replay, CSV import/export; TWR, XIRR, drawdowns, volatility, beta, correlations, rebalance and stress | No broker CSV presets; cash earns no interest |
| Research | Statements and ratios with sources; screener + peers + heatmap; earnings calendar, reported changes, filing diffs, guidance quotes; valuation lab (DCF, multiples, sensitivity); macro watchboard; research lab (rule tests, paper portfolio); research export | No historical fundamentals (no point-in-time tests); no consensus estimates |
| Alerts + worker | Price, cross, volume, volatility, filing and earnings rules; cooldown/rearm, quiet hours, unique keys; inbox; scheduled briefings; single worker | No email/Telegram/push |
| AI | Evidence-first cited answers (ask, results, catalysts, compare, brief) on Groq's free tier (or xAI), with code checks, server caps, owner quotas, reuse | No web search |
| Ops | Owner login (argon2, signed cookie, CSRF, rate limit), request IDs, health/readiness/status, backup/restore, migrations 0001–0012 rehearsed on production copies, PWA shell, usage panel | Render Free sleeps when idle (alerts only while awake) |

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

## M06 — Screener and peers (4 Nov 2026)
- **Universe:** all watchlists, one watchlist, current holdings, or a pasted list (verified symbols, ≤ 150; skipped
  symbols listed with the provider's reason). Indices and currencies are left out and named. Every result states the
  universe, its member count, how many have data, and the oldest snapshot.
- **Snapshot:** `screen_metrics` holds, per instrument, 17 metrics (price/returns, 52-week distance, 20-session volume and
  traded value, market cap, P/E, P/B, dividend yield, FY revenue growth, net margin, ROE, debt/equity, 1Y volatility)
  as decimal strings or null with the reason, each with its as-of date, plus the status/source/fetch time of each
  input. Built through the cached market service by "Load data" (≤ 60 per request, one job at a time) and by the
  worker (6 stale per cycle across watchlists, holdings, lists and peer groups). Screens never call the provider.
- **Annual statements:** new provider method (Yahoo `get_income_stmt`/`get_balance_sheet`; fixture
  `fixtures/market/financials.json`, generated deterministically) cached 24 h; only ratios within one statement set
  are used because the endpoint does not report the statement currency. Debt/equity is withheld for financial-services
  companies; negative equity makes ROE and debt/equity "not meaningful".
- **Filters:** ≥ / ≤ / between on any metric, plus market, sector, industry, currency, exchange. Missing values never
  pass; each filter reports passed / failed / no data. Currency amounts take a unit (₹ Cr/lakh, $ B/M) and compare
  other-currency listings at the stated USD/INR rate. Sorting keeps missing values last.
- **Saved screens** (name, universe, filters, sort; opened from the URL), **CSV export** (formula-safe cells, universe
  footer), **add selected results to a watchlist**, **preview** with every metric's period, formula and inputs.
- **Sector heatmap:** 1D/1M/3M/1Y, equal or market-cap weighted (INR at the stated rate; falls back to equal weights,
  with a notice, when no rate is available for a mixed universe), member table as the text alternative.
- **Peers** (Instrument → Peers): up to five chosen peers (verified, no self, no indices) or suggestions from tracked
  instruments in the same industry, then sector, nearest market cap; side-by-side table with snapshot age; reset to
  suggestions.
- **Schema:** migration 0008 adds `screen_universes`, `saved_screens`, `peer_sets` (owner data, in backups) and
  `screen_metrics` (rebuildable, excluded from backups). Rehearsed on a copy of production (schema 0007 backup):
  restored, migrated to 0008, owner-data fingerprints identical.
- **Also fixed:** the test suite now removes real AI/SEC credentials from its environment (a developer's `GROK_API`
  made one test fail and could have reached a real provider).

| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 17 | 229 passed, 3 skipped / 231 passed, 1 skipped (M06: 10 — snapshot values, units and reasons; leverage/profitability edge cases; missing never passes; currency comparison; Yahoo statement frames; full screen flow incl. export; saved screens and lists; heatmap weighting; peers; holdings universe and worker refresh; backups) |
| ruff, tsc, eslint, vitest | clean; 32 frontend tests |
| Migrations match models (SQLite, PostgreSQL); downgrade 0008→0007 and upgrade | pass |
| CI (928a944) | green |
| Playwright | 17 journeys pass (new: named list → load data → P/E filter excludes a negative-earnings company with the count shown → save → reopen → preview → add to watchlist → heatmap → peers) |
| Visual QA | Screener, heatmap and peers at 1440, 1024 and 390 px inspected; fixed wrapping market caps, stacked filters below 1280 px, wrapped toolbar at 390 px, full-contrast heatmap values. `docs/screenshots/screener-1440.png`, `peers-1440.png`, `heatmap-390.png` |

**Live verification after deploying 928a944 (4 Nov 2026).**
- Production migrated to 0008 on deploy (status `current 0008, up to date`), after the rehearsal above; a fresh
  backup was taken first.
- The worker built snapshots for all three watchlist members in its first cycle ("Load data" then found nothing due).
  Coverage: price, returns, 52-week distance, volume, traded value, market cap, P/B, revenue growth, net margin, ROE
  and volatility 3/3; P/E 2/3 ("not reported", a loss-making company); dividend yield 1/3; debt/equity 1/3 (withheld
  for a lender; one company without a total-debt line). Yahoo annual statements loaded for all three from Render.
- A P/E ≤ 40 screen: 1 pass, 1 fail, 1 no data (excluded and counted). Market-cap-weighted heatmap combined INR and
  USD listings at the stated USD/INR rate. Peers: no suggestions yet (the three companies are in different sectors),
  as designed.
- Read-only browser check at 1440 and 390 px (light theme, real data): no console errors or failed API calls, no page
  overflow; the phone layout uses summary rows.

## M09 — Performance, risk and rebalancing (4 Nov 2026)
- **Valuation series** (`services/risk_math.py`, pure): daily cash + quantity × as-traded close; provider split history
  restores as-traded prices and ledger SPLIT entries change quantity (no double counting; a provider split missing
  from the ledger is flagged); holiday gaps carried ≤ 10 days, longer gaps left out with reasons, flows moved forward.
- **Returns:** time-weighted (daily, flows at the end of the day) and money-weighted (XIRR), annualized only for ≥ 1
  year; benchmark (price index, selectable) total, annualized and difference; best/worst day.
- **Risk:** annualized volatility (≥ 60 returns), drawdown series with peak/trough/recovery, beta and correlation to
  the benchmark only when every holding shares its exchange time zone.
- **All accounts:** USD converted at each day's USD/INR close; FX conversions internal.
- **Exposure:** by holding, sector, market, currency; largest, top five, HHI, effective holdings; unpriced listed.
- **Correlations:** holdings (≤ 12) + benchmark over one year; daily returns on common dates within a time zone,
  weekly across time zones; minimum 60 / 26 observations; n shown per cell.
- **Rebalance:** targets per account (migration 0009, `allocation_targets`), simulation with added cash, whole shares
  and an assumed fee; share counts editable on the page; nothing is recorded or submitted.
- **UI:** Portfolio → "Holdings & ledger" | "Performance & risk" | "Rebalance" (URL `section=`); growth-of-100 and
  drawdown charts with a daily table alternative and a "How these are calculated" list; All accounts → Performance.
- **Schema:** 0009 rehearsed on a production copy (0008 backup): restored, migrated, owner-data fingerprints identical.

| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 17 | 239 passed, 3 skipped / 241 passed, 1 skipped (M09: 10 — hand-checked TWR vs MWR vector, split restoration and carry window, drawdown/recovery, volatility threshold, aligned and weekly correlations, rebalance vector incl. rounding toward zero and negative cash, API consistency with the holdings view, unrecorded split warning, exposure/targets/simulation, consolidated FX) |
| Migrations match models (SQLite, PostgreSQL); downgrade 0009→0008 and upgrade | pass |
| tsc, eslint, vitest | clean; 32 |
| Playwright | 18 journeys pass (new: performance & risk with table alternative and methods, exposure by sector, correlation table, targets → simulation → edited shares, ledger unchanged) |
| Visual QA | Performance, exposure, correlation and rebalance at 1440 and 390 px inspected; fixed tiny "₹0.01 Cr" amounts (whole rupees below a crore), inline benchmark picker, shorter fee label |

**M09 live verification (after deploying 23caf84, 4 Nov 2026).** Production migrated to 0009 on deploy (rehearsed
first). The owner's ledger has no transactions yet, so performance (INR, USD, all), exposure and correlations return
their explained "nothing yet" states; targets and the simulation endpoint respond (empty, "no orders are placed").

## M11 — Valuation lab (4 Nov 2026)
- **DCF** (`services/valuation_math.py`, pure): equity two-stage DCF with Gordon terminal value; inputs validated
  with field-level reasons (r 1–40%, g −50–100%, g_T −5–10% and ≥ 0.5 pp below r, N 1–15, FCF > 0, shares > 0);
  outputs: per-year FCF, discount factors, PVs, terminal value and its share, equity value, value per share, vs price.
- **Defaults with sources** (`services/valuation.py`): FCF = OCF − capex of the latest fiscal year (annual statements
  now include operating cash flow, capex and cash — Yahoo cash-flow statement, deterministic sample values); shares
  implied from market cap ÷ price; growth from revenue growth limited to 0–15%; rates labelled assumptions; a
  negative latest FCF is flagged. Not applied to financial-services companies (explained; peer P/B offered instead).
- **Sensitivity** 5 × 5 over two of discount rate, terminal growth, forecast growth; invalid cells "n/a" with reason.
- **Peer multiples:** P/E and P/B ranges (min, quartiles, median, max) × own EPS/BVPS from the M06 peer group.
- **Scenarios** (migration 0010 `valuation_scenarios`): bear/base/bull/custom with notes; load, update, delete; "Ask
  AI" opens the research dialog with a prefilled, cited question about the assumptions.
- **Stress test** (Portfolio → Performance & risk): market and USD/INR shocks with presets on current holdings and
  cash; per-holding effect; consistent with the overview total.
- **Schema:** 0010 rehearsed on a production copy (0009 backup): restored, migrated, owner-data fingerprints identical.

| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 17 | 260 passed, 3 skipped / 262 passed, 1 skipped (M11: 21 — DCF hand vector, 9 rejected assumptions, parsing, sensitivity centre/invalid cells/monotonicity, multiple ranges, stress vector, pre-M11 cache entries, defaults with sources and bank refusal, DCF run, multiples via the peer group, scenarios CRUD, stress vs overview, backups) |
| Migrations match models (SQLite, PostgreSQL); downgrade 0010→0009 and upgrade | pass |
| tsc, eslint, vitest | clean; 32 |
| Playwright | 19 journeys pass (new: valuation lab — sourced defaults, rejected terminal growth, sensitivity table, saved scenario with AI button, bank refused; stress test preset) |
| Visual QA | Valuation and stress test at 1440 and 390 px inspected; added readable amounts beside raw inputs ("= ₹1,888.60 Cr"), hid peer names on phones |

**M11 live verification (after deploying 7449a73, 4 Nov 2026).** Production migrated to 0010 (rehearsed first).
Valuation inputs for the watchlist stocks returned their defaults with sources (shares implied from market cap and
price; growth from revenue growth); the financial-services stock (IFCI.NS) was correctly refused a generic DCF. Base free
cash flow showed "not reported" because statements cached before M11 lacked the new cash-flow lines; the statements
cache key was versioned in the next commit so they are fetched again at once.

## M07 — Earnings and filing analysis (4 Nov 2026)
- **Calendar** (`services/earnings.py`): past results dates from SEC 8-K Item 2.02; next date estimated from the
  cadence of past results filings (US, ±7 days, only when quarterly-like) or the SEBI LODR 33(3) deadline (India);
  never presented as announced; no consensus figures. Universe view (watchlists, holdings, lists, peers, alerts).
- **Results reminders:** alert rule EARNINGS (0–30 days before; once per date; inbox), evaluated by the worker.
- **Reported changes:** YoY and QoQ from SEC quarterly facts (three-month durations), FY from annual facts or the
  provider's statements; margins in pp; restated values marked; links to filings.
- **Filing changes:** Item 1A paragraphs added/removed/reworded (≥ 60% similarity) between the latest two 10-K/10-Q,
  quoted. **Guidance:** quoted guidance/outlook sentences with figures from recent results releases.
- **AI brief:** new research task "brief" (bull/base/bear with explicit assumptions, cited; no targets).
- **No schema change.**

| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 17 | 268 passed, 3 skipped / 270 passed, 1 skipped (M07: 8 — cadence estimates, SEBI deadlines incl. year end, QoQ/YoY with restatements and no substitute periods, quoted risk-factor diff, guidance extraction, API on sample data, reminder fires once, brief task) |
| tsc, eslint, vitest | clean; 32 |
| Playwright | 20 journeys pass (new: earnings — deadline label and SEBI rule, fiscal-year changes, reminder alert, brief preset, upcoming results) |
| Visual QA | Earnings tab at 1440 and 390 px inspected (no overflow) |

## M12 — Macro and sector context (4 Nov 2026)
- **Watchboard** (`services/macro.py`): 15 Yahoo series (benchmarks, volatility, US yields, FX, commodity futures; the
  sample dataset's 3 series in fixture mode) with provider, frequency, observation date, revision status, 1D/1W/1M/
  3M/1Y changes (yields in pp; start dates named; no substitute when history is too short) and a 60-session sparkline.
- **Official statistics / release calendar:** listed as not configured (FRED key) or not verified (RBI/MOSPI) — not
  approximated.
- **What moved:** deterministic largest moves over a window with values, dates and the owner's linked companies.
- **Sector-relative:** return vs equal-weighted sector average (≥ 2 members) and vs the market benchmark.
- **Exposure map** (migration 0011 `macro_links`, owner data): company ↔ series links with relation, direction and
  note; descriptive correlation with n and method.
- **Schema:** 0011 rehearsed on a production copy (0010 backup): restored, migrated, owner-data fingerprints identical.

| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 17 | 274 passed, 3 skipped / 276 passed, 1 skipped (M12: 6 — pp vs % changes and no substitutes, briefing order and owner links, watchboard API, sector-relative view, links with correlation, backups) |
| Migrations match models (SQLite, PostgreSQL); downgrade 0011→0010 and upgrade | pass |
| tsc, eslint, vitest | clean; 32 |
| Playwright | 21 journeys pass (new: macro — labels, official statistics not approximated, link with correlation, briefing shows the link) |
| Visual QA | Macro page at 1440 and 390 px inspected (no overflow) |

## M13 — Research lab: rule tests and paper portfolio (4 Nov 2026)
- **Engine** (`services/sim_math.py`, pure): signals use closes up to the decision day only; execution at the next
  session's open × (1 ± slippage), fee % from cash, whole shares, long-only; dividends on the adjusted basis credited
  when held at the prior close; CAGR only over ≥ 365 days; volatility only with ≥ 60 returns.
- **Run ledger** (migration 0012 `research_runs`): rule, parameters, costs, provider, dates, bars and a SHA-256 data
  fingerprint; *Reproduce* compares data and results.
- **Paper portfolio** (0012 `paper_portfolios`, `paper_orders`): isolated from the ledger; orders fill at the first
  session after the placement session or stay pending (cancellable); rejections give the reason.
- **UI:** Lab page (G L; More menu on phones) with Rule test, Run ledger, Paper portfolio and Read me; results table,
  equity chart (rule vs hold, ends on the table's values), trade list.
- **Schema:** 0012 rehearsed on a production copy (0011 backup): restored, migrated, owner-data fingerprints identical.

| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 17 | 284 passed, 3 skipped / 286 passed, 1 skipped (M13: 8 — no look-ahead in signals, next-open + costs hand vector, adjusted dividends and fingerprint, drawdown, paper fills/rejections/pending, API run recorded and reproducible, paper isolated from the ledger, backups) |
| Migrations match models (SQLite, PostgreSQL); downgrade 0012→0011 and upgrade | pass |
| tsc, eslint, vitest | clean; 32 |
| Playwright | 22 journeys pass (new: research lab — run, reproduce, paper order pending) |
| Visual QA | Lab page at 1440 and 390 px inspected (no overflow; mobile table drops two columns) |

**Live (Render + Neon, Yahoo, schema 0012):** read-me items listed; RELIANCE.NS moving-average cross 20/50 (0.1% fee,
5 bps): 1,235 bars 2021-11-04 → 2026-11-03, benchmark ^NSEI, 30 trades, every signal day before its execution day,
chart ends on the table value, *Reproduce* → identical data and results. AAPL momentum 60: benchmark ^GSPC, same
checks. Paper portfolio: a RELIANCE.NS order placed after the 2026-11-03 session is pending for the next open; a USD
instrument in the INR paper account is refused (`currency_mismatch`). The live check then deleted its runs and paper
portfolio; the real ledger was unchanged. Two fixes followed: the dividend count/fingerprint now covers only the tested
window (Yahoo returns all-time dividends: AAPL showed 92), and an unfinished latest session is left out of rule tests
(its "close" is only the latest price); paper fills keep the conservative rule (an order placed during a session fills
at the next session's open).

## M14 — Workspaces, offline copy, exports, usage (5 Nov 2026)
- **Workspaces** (`services/workspaces.py`, `app_settings`): presets with start page, density, default watchlist and
  chart symbol; switch from the top bar, the phone More sheet or the palette; "save the current layout"; a deleted
  default watchlist is reported, not recreated; at least one workspace is kept.
- **PWA:** manifest, icons, `sw.js` (network-first shell, cache-first hashed assets, never `/api`; served
  `no-cache`). **Offline copy:** opt-in per device, first five watchlists + holdings, refreshed every 10 minutes while
  open; shown only when the server is unreachable as "Offline copy · read-only · not live" with its sync time; erased
  on sign-out, on 401 and when turned off. A banner explains when the browser reports no network.
- **Research export** (`/api/export/research`, Markdown, `no-store`): quote, fundamentals with units, corporate
  actions, SEC filings (US), saved AI answers with retrieved sources; journal and holding are opt-in private sections
  named in the header.
- **Usage** (`/api/usage`): provider requests by kind since process start (asked, cache hits, upstream, failed, stale
  served), circuits, cache lives, SEC status, AI use vs effective limits. **Quotas** (`PUT /api/usage/quotas`): the
  owner's daily answer/token/USD limits, only below the server caps, enforced in the reservation step.
  **Refresh preference:** quotes and valuations every 30 s – 5 min or manual.
- **Keyboard:** palette actions for workspaces, theme, density, export, usage; existing G-shortcuts.
- **Schema:** none (preferences and presets are `app_settings` rows, included in backups).

| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 17 | 291 passed, 3 skipped / 293 passed, 1 skipped (M14: 6 — presets persist/apply/validate, refresh preference, usage counters and quotas that only tighten, quota enforced at reservation, export private sections off by default, sign-in required) |
| tsc, eslint, vitest | clean; 35 (new: offline copy off by default, erased on clear/turn-off, corrupt copies ignored) |
| Playwright | 25 journeys pass (new: workspaces switch/reload/save/palette; research export with and without private sections; offline copy served by the service worker while offline, labelled, then erased) |
| Visual QA | Settings (workspaces, usage) at 1440 and 390, workspace menu, export dialog, offline view at 390 inspected; fixed: section scroll under the sticky bar, stretched notice, cramped offline header on phones |

## Final release check (5 Nov 2026)
Every milestone's "Done when" from `docs/MARKETDESK_ROADMAP.txt`, against the evidence recorded above.

| Milestone | Done when | Result | Evidence |
| --- | --- | --- | --- |
| M00 Operational foundation | Login and persistence work in production; no secrets in errors; backup restores to a separate database | ✅ | Live login, request IDs, backups restored to local PostgreSQL before every schema change (0002–0012) |
| M01 India + US | Symbols disambiguated; native currency; holidays/DST give no false "open" | ✅ | Calendar tests incl. DST; live identity checks |
| M02 Company workspace | Every figure traceable to period, unit, source, update date; missing explicit | ✅ | SEC companyfacts with periods/units/forms; live SEC verification |
| M03 Cited analyst | Answers tied to evidence; maths in code; unsupported claims flagged; no key → AI off | ✅ | Validation tests (unknown sources, figures not in sources); live Groq answers |
| M04 Streaming | Disconnects, gaps, duplicates, limits; IEX not called consolidated | ✅ done (11 Nov 2026) | Alpaca IEX websocket → SSE; DECISIONS #65; tests/test_alpaca.py, tests/live.test.ts |
| M05 Alerts and review | Restarts don't duplicate; stale data can't trigger; failed delivery visible | ✅ | Idempotency and stale-quote tests; live worker cycles |
| M06 Discovery and peers | Cached normalized data; missing ≠ pass/zero; universe named | ✅ | Screener tests; live snapshot refresh |
| M07 Earnings and filings | Annual/quarterly/YTD never mixed; restatements distinguishable | ✅ | Period tests; live calendar, changes, SEBI deadline, 10-K risk-factor diff (after the fixes below) |
| M08 USD and FX | INR holdings unchanged; no relabelling; missing FX → no unqualified total | ✅ | Migration fingerprints identical; FX tests |
| M09 Risk and performance | Documented formulas, test vectors, enough observations, stated policies | ✅ | Hand vectors (TWR, XIRR, beta tz rule) |
| M10 Decision journal | Originals immutable/versioned; edits explicit; snapshots not replaced | ✅ | Version/snapshot tests |
| M11 Valuation lab | Deterministic, tested, labelled inputs, invalid assumptions rejected, hypothetical | ✅ | DCF/sensitivity vectors; live refusal for banks |
| M12 Macro and sector | Provider, frequency, observation date, release date where available, revision status | ✅ (market series); official statistics not configured | 15 live Yahoo series; FRED/RBI/MOSPI listed as not configured, not approximated |
| M13 Research simulation | Simulated labels; signal before execution; splits/dividends; reproducible | ✅ | Hand vectors; live RELIANCE.NS/AAPL runs reproduced identically |
| M14 Workspace polish | Presets survive reload; offline can't pass as live; private caches clear on logout; keyboard/mobile usable | ✅ | Journeys (reload, offline via service worker, palette); 390 px QA; sign-out/401/turn-off erase the copy |

**Checks run at release:** ruff; pytest SQLite 293 passed / 3 skipped (after the fixes) and PostgreSQL 17 293 passed / 1 skipped (before them);
migrations match models (SQLite, PostgreSQL); tsc, `eslint .` (as CI), vitest 35; production build; Playwright 25
journeys; tracked-secret scan (only fake test strings and `.env.example`); no TODO/placeholder handlers.
**Production smoke (Render + Neon):** health and readiness 200; unknown `/api` route → JSON 404; SPA deep links serve
the shell; private endpoints 401 without a session (portfolio, workspaces, usage, export, lab); anonymous writes 401;
CSP present; session cookie Secure and HttpOnly; schema 0012 current; worker running (yahoo, 234 cycles, no error).
**Defects found by the check and fixed:**
1. CI failed on the M14 commit: ESLint ran over `public/sw.js` without service-worker globals (fixed in 2156509).
2. The live 10-K risk-factor comparison timed out (> 280 s for AAPL and SMR). Two causes: filing HTML lost its
   paragraph breaks (inline-XBRL reports have few source line breaks and every tag became a space, so a whole
   Item 1A was one "paragraph"), and rewording was found by character-level matching of every paragraph pair.
   Block tags now end lines (source wrapping does not), and a word-pair shortlist feeds a word-level comparison
   (f894efc, 00cd85b; tests for both). Live after the fix: SMR 10-K 300 vs 283 paragraphs (79 added, 96 removed,
   112 reworded) in 5 s; AAPL 99 vs 115 (28 added, 13 removed, 53 reworded) in 4 s, all quoted from the filings.

## Terminal T1 — Description view and function codes (5 Nov 2026)
- **API** `GET /api/terminal/description?symbol=` (`services/description.py`): identity (listing, identifiers,
  related listings sharing a CIK/ISIN, SEC profile with all tickers, fiscal year end), business summary (10-K Item 1
  opening paragraphs, quoted, cached per accession; else the provider profile marked "not verified"; else the reason),
  key statistics from the M06 snapshot (rebuilt when stale) with as-of dates and formulas, and a coverage list for
  15 domains with status, source and reason.
- **Provider:** `Fundamentals.summary` (Yahoo `longBusinessSummary` when Yahoo serves it; the sample dataset says its
  companies are fictitious). Cached entries without it still decode.
- **UI:** Description is the landing tab (chart, key statistics, business, identity, events, latest filings, peers,
  coverage; coverage becomes a stacked list on phones); the former overview is the Chart tab (`?tab=overview` links
  still work). Function codes in the palette (`SYMBOL CODE`, the code alone on an instrument page, `?` to list) and
  in the shortcuts dialog.
- **Fixes found on the way:** two requests registering the same new listing, or storing the same snapshot, at once
  raised unique-constraint errors (the landing view loads several panels together); both now retry against the
  stored row.
- **Schema:** none.

| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 17 | 298 passed, 3 skipped / 300 passed, 1 skipped (T1: 5 — Item 1 extraction skips the table of contents and quotes whole paragraphs, SEC summary cached per accession, API on sample data with reasons for every gap, country-specific coverage, old cache entries decode) |
| tsc, `eslint .`, vitest | clean; 37 (new: function-code parsing and URLs) |
| Playwright | 26 journeys pass (new: description tiles and coverage, `glasswing fa`, `?`, `dvd`, `hds` → coverage) |
| Visual QA | Description at 1440 and 390 px, palette code list, mobile coverage and identity inspected |

**Live (Render + Neon, Yahoo + SEC):** AAPL — business quoted from the 10-K filed 2026-11-03 (Item 1, with link),
SEC CIK 320193, SIC 3571, fiscal year end 09-26, all 18 statistics present; SMR — 10-K (filed 2026-02-26) quoted,
P/E, dividend yield and debt/equity missing with reasons; RELIANCE.NS — no business text (Yahoo refuses its company
summary from the server; the reason is shown), statistics present, coverage marks filings/insiders/holders as needing
a permitted Indian source and results dates as the SEBI deadline. Each response took about 2 s.

## Terminal T2 — Financial analysis depth (5 Nov 2026)
- **Statements:** ten annual / twelve quarterly columns where filed (`/api/research/financials?periods=`); new SEC
  lines: income before tax, income tax, diluted weighted-average shares, current debt, depreciation and amortization.
- **Analysis** (`services/fin_analysis.py`, pure; `GET /api/terminal/financial-analysis`): margins, YoY growth,
  3/5/10-year CAGR, ROE/ROIC/tax rate/cash conversion, per-share, common-size; every row carries its formula and
  every gap its reason. Provider statements (non-SEC listings) run the same analysis, labelled unofficial.
- **Valuation bands:** daily P/E and EV/EBITDA over five years, point in time by filing date, split-aware, never
  mixing currencies; min/quartiles/median/max/latest/percentile.
- **UI:** Financial analysis and Valuation bands panels under the statements; measures a source never reports are
  listed by name rather than shown as empty rows.
- **Schema:** none.

| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 17 | 303 passed, 3 skipped / 305 passed, 1 skipped (T2: 5 hand vectors — per-share/common-size/margins, growth and CAGR rules, ROE/ROIC with the tax-rate rule, point-in-time bands across a 2-for-1 split, provider path via the API) |
| tsc, `eslint .`, vitest | clean; 37 |
| Playwright | 27 journeys pass (new: financial analysis on sample data — margins, growth, CAGR reason, absent measures listed, unofficial label, bands reason, quarterly note) |
| Visual QA | Financial analysis at 1440 and 390 px (tables scroll inside; source line moved into the body) |

**Live (SEC + Yahoo):** AAPL — 10 fiscal years and 12 quarters; diluted EPS FY2023 6.13, FY2024 6.08, FY2025 7.46,
FY2026 8.98; gross margin FY2025 46.9%; revenue CAGR 7.7% (3 y) / 5.5% (5 y), 10 y "fewer than 10 years reported";
P/E band over 1,255 sessions 20.5–46.8× (median 31.7×, latest 38.3×, 82nd percentile); EV/EBITDA 16.3–36.5×
(latest 29.8×). SMR — 7 fiscal years; losses, so P/E and EV/EBITDA bands and EPS CAGR show their reasons; ROIC
unavailable (tax rate not meaningful). RELIANCE.NS — Yahoo's four fiscal years labelled unofficial (net margin
7.6%, ROE 8.9%, revenue CAGR 6.4% over 3 y); bands not shown with the reason. Each call took 0–3 s.

## Terminal T6 — Relative value and risk (5 Nov 2026)
- **API** `GET /api/terminal/risk?symbol=&benchmark=&universe=` (`services/security_risk.py`): beta, correlation
  and R² (1 y, 3 y; daily in one time zone, weekly across), volatility, drawdown profile (current, 1/3/5-year maximum,
  deepest declines with recovery), liquidity (20/60-session volume, traded value, median daily high–low range),
  z-scores and percentiles within a declared universe (stored snapshots), peer P/E history (US, from T2 bands), and
  short interest.
- **Short interest:** `providers/finra.py` (OAuth client credentials; JSON; symbol filter; local sort; 12-hour cache;
  FINRA named as source). FINRA's terms require credentials, so it is **off and unverified** until the owner sets
  `FINRA_CLIENT_ID` / `FINRA_CLIENT_SECRET` (free Individual account → Public credential). One anonymous test request
  showed the dataset exists; the adapter never uses anonymous access.
- **UI:** Risk tab (codes `BETA`, `SI`), benchmark picker and universe selector in the URL; Description coverage
  links short interest to the Risk tab and shows whether FINRA is configured.
- **Schema:** none (short interest is cached in the existing market cache table).

| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 17 | 312 passed, 3 skipped / 314 passed, 1 skipped (T6: 9 — beta 2.0/correlation 1 hand vector and weekly fallback, drawdown episodes with recovery, median daily range vector, z-score/percentile vector, FINRA token (Basic) → Bearer JSON query with fallback spelling and token caching, credential gate, API on sample data, universe validation) |
| tsc, `eslint .`, vitest | clean; 37 |
| Playwright | 28 journeys pass (new: risk — `beta` code, benchmark sensitivity, deepest declines, liquidity note, universe position, short interest reason, benchmark changed to SX:BANYAN) |
| Visual QA | Risk tab at 1440 and 390 px (small universes show one notice; drawdown figures in two columns) |

**Live (Yahoo + SEC):** AAPL vs ^GSPC — beta 0.63 (1 y, 250 daily returns) / 1.06 (3 y), correlation 0.34 / 0.59;
volatility 24.9% / 27.0%; deepest decline −33.4% from 26 Dec 2024 to 8 Apr 2025, recovered 20 Oct 2025; peer P/E
ranges for AAPL, NVDA and PANW from filed EPS. RELIANCE.NS vs ^NSEI — beta 0.99 / 1.11; decline of −27.7% since
8 Jul 2024 not yet recovered. SMR — beta 3.8 (1 y), volatility 94%, −91.7% from its October 2025 high; P/E history
not meaningful (losses). Short interest: "not configured" (US) / "not applicable" (India) as intended. The owner's
watchlists hold 2–3 instruments, so z-scores show the "at least 5 members" notice. The first version showed an
Abdi–Ranaldo spread estimate (≈0.8% for RELIANCE.NS, 0% for AAPL — unrealistic); it was replaced by the median
daily high–low range before release.

## QA pass and interaction polish (9 Nov 2026)
Owner request: go through the whole repository once, full QA, and make the front end as interactive and friendly as
possible. Method: a Playwright sweep (`tests/e2e/qa-sweep.spec.ts`, run with `QA_SWEEP=1`) of 29 views and 11 dialogs
at 1440/1024/768/390 px — full-page screenshots (inspected), horizontal-overflow check, axe-core WCAG 2.1 A/AA audit,
console errors, page errors and failed API responses — plus every automated suite.

**Found and fixed**
- Accessibility: 19 horizontally scrolling tables (statements, analysis, risk, valuation, earnings, performance,
  usage, dialogs) were not reachable by keyboard → focusable, with an edge shadow where columns are hidden; inline
  links distinguished by colour only (contrast 1.3:1 with the surrounding text) → underlined; `<p>` inside a `<dl>`
  on Settings → restructured; the CSV file input had no label → labelled; dialog bodies become a tab stop only when
  they scroll.
- Clickable table rows (watchlists, holdings, screener, peers…) could not be opened from the keyboard, and the phone
  summary rows were plain `div`s → keyboard rows (Tab, ↑/↓, Enter/Space, visible focus), `role=button` on phones.
- An unknown symbol fired nine failed API requests (every panel queried before the quote resolved) → one.
- 768 px: the top-bar workspace label wrapped and pushed the title down → single line; the Overview watchlist
  selector truncated list names → widened; the Journal review queue squeezed titles to a few letters on phones →
  two-line rows; stress-test presets looked like plain text → buttons; a doubled full stop in analysis notes.
- Removing a symbol from a watchlist had neither confirmation nor undo → Undo in the toast (a real re-add; the
  notice is an option-level mutation callback because the row unmounts).

**Interaction improvements**
- Pages load as separate chunks (main bundle 662 → 388 kB, 119 kB gzipped) with a skeleton while a chunk loads.
- Command palette: recently viewed instruments (per device, cleared at sign-out) when nothing is typed; actions
  pre-filled with the current instrument ("Create alert for AAPL", "New note on AAPL", "Add transaction for AAPL").
- Instrument tab strip on phones: the selected tab scrolls into view, edge fades show hidden tabs, Home/End keys.
- Toasts can carry an action; an axe accessibility check over 14 main screens is now part of the Playwright suite.

| Check | Result |
| --- | --- |
| QA sweep (29 views × 4 widths + 11 dialogs × 2 widths) | no horizontal overflow anywhere; axe: 0 violations of any impact after the fixes (before: 3 serious patterns on 7 views, 1 critical in a dialog); console: only the expected 422 for an unknown symbol, now 1 per load instead of 9 |
| pytest SQLite / PostgreSQL 17 | 312 passed, 3 skipped / 314 passed, 1 skipped (backend unchanged) |
| tsc, `eslint .`, vitest | clean; 41 (new: recently-viewed store incl. limit, corrupt storage, forget; DataTable keyboard rows) |
| Playwright | 30 journeys pass (new: interaction polish — keyboard rows, Undo, palette recents and prefilled action, tab-strip fade; accessibility — no serious/critical axe violations on 14 screens) |
| Visual QA | before/after captures inspected at 1440, 1024, 768 and 390 px (Overview, Watchlists, Screener and heatmap, Macro, Lab, Instrument tabs, Portfolio and performance, Alerts, Journal, Settings, dialogs) |

## Terminal T4 — Earnings and corporate events (10 Nov 2026)
- **API** (`services/events.py`, routes under `/api/terminal`): `GET /events?symbol=` — one security's past and
  upcoming events, each with kind (results, dividend, split, report, proxy, meeting, buyback), status (confirmed,
  estimated, deadline, mention), source, link and, where quoted, the sentence it came from; `GET /events/universe?
  universe=&ahead=&back=` — the same across all watchlists, one watchlist, a screening list or holdings within a
  window (7–180 days ahead, 0–90 back; at most 60 listings scanned, failures listed per symbol); `GET
  /earnings-history?symbol=` — reported revenue, net income and diluted EPS by period with the change on a year
  earlier, from SEC company facts (US, quarterly, official) or the provider's annual statements (unofficial).
- **Sources:** 8-K Item 2.02 and periodic filings, DEF 14A proxies (the annual-meeting date is quoted from the notice
  and accepted only between a week before and 150 days after the filing), 8-K results releases (sentences that mention a
  repurchase programme, marked "mention"), the price provider's dividends and splits, and the SEBI deadline for Indian
  listings. Each filing is read once and the scan cached per accession in the market cache. Indian board meetings,
  AGMs and buybacks are not fetched (no permitted source); the view says so. Consensus estimates and surprises are
  licensed data and are not shown — the UI explains why.
- **UI:** the Events tab is now the T4 calendar (Upcoming with status marks; Past events with kind filter chips, quotes
  in a disclosure, sources and notes) — it replaces the M02 "Filing events" + "Corporate actions" panels; an Earnings
  history table on the Earnings tab (values link to their filings, year-on-year change computed here, R = restated);
  a Corporate events panel on the Alerts page (universe and window selectors) next to Upcoming results; function code
  `CACS` (DVD still opens the same tab).
- **Schema:** none.

| Check | Result |
| --- | --- |
| pytest SQLite / PostgreSQL 16 | 321 passed, 3 skipped / 323 passed, 1 skipped (T4: 9 — proxy meeting date quoted and bounded to the filing window, case and zero-width tolerant, stray dates rejected; buyback sentences without boilerplate; history rows with YoY and restatement flags; past/upcoming split with de-duplication; deadline vs estimate labels; fake-SEC builder with proxy, release, reports and per-document caching; API on sample data; universe window and validation; annual history with YoY) |
| tsc, `eslint .`, vitest | clean; 41 |
| Playwright | 31 journeys pass (new: events — `CACS` code, SEBI deadline marked as a deadline, dividend rows with sources, kind filter hides and restores, earnings history table with YoY, Corporate events on Alerts with a 120-day window) |
| Visual QA | Events tab and Alerts page at 1440 and 390 px (`docs/screenshots/events-*.png`); no horizontal overflow |

**Live (Yahoo + SEC) after deploying 4986d6e (10 Nov 2026), read-only.** AAPL: 135 past events (92 dividends back to
1987, 5 splits, 24 periodic reports, 8 results filings, 2 proxies, 2 meetings, 2 buyback mentions) and a next-results
estimate of 1 Feb 2027; annual meeting 24 Feb 2026 quoted from the proxy filed 8 Jan 2026; the 30 Apr 2026 release
quoted "authorized an additional program to repurchase up to $100 billion"; first load 30 s (two proxies and eight
releases read from EDGAR on the Render Free instance), cached afterwards. SMR: 8 results filings, 14 reports, meeting
29 May 2026 from the proxy of 15 Apr 2026, no dividends. RELIANCE.NS: SEBI deadline 14 Feb 2027 for the quarter ended
30 Sep 2026, 31 dividends and 4 splits from Yahoo, the "needs a permitted exchange source" note for meetings. Earnings
history: AAPL quarterly from SEC facts with year-on-year change (e.g. quarter to 27 Jun 2026: revenue +16.4%, diluted
EPS +28.7%); RELIANCE.NS annual, unofficial, with change. Universe calendar over the owner's three watchlisted
listings: 2 ahead, 1 behind, none failed. Follow-ups from the check: the meeting quote began at the regex match (a
heading or an earlier date) rather than around the date — now quoted around the date from a sentence boundary, with
the proxy-scan cache key versioned so cached scans are redone once; proxy and release documents are read concurrently;
past lists longer than 30 rows page with "Show more". The first version of that concurrency used the request's
database session from several threads at once (AAPL's ten documents): CI failed with SQLAlchemy's
`IllegalStateChangeError` and the live AAPL events call returned 500 for a few minutes. Fixed the same hour: cache
reads, then at most four concurrent fetch-and-scan tasks, then cache writes, all on one thread at a time; the fake-SEC
test now sleeps in document reads so the overlap is exercised. Proxies for special meetings are labelled as such (SMR's
16 Dec 2025 special meeting had been labelled annual).

## Visual redesign: animated "aurora glass" identity (11 Nov 2026)
Owner request (DECISIONS #55). New palette and effects layer in `styles/index.css`, helpers in `lib/fx.tsx`, applied
through the shared components (Panel, Button, Metric, Sparkline, Toast, Dialog) and the shell, so every page changes.
Settings → Appearance → Visual effects (Full/Calm, per browser); reduced motion respected. No backend or schema change.

| Check | Result |
| --- | --- |
| tsc, `eslint .`, vitest | clean; 41 |
| Playwright | 31 journeys pass, including the axe accessibility check (one journey now waits for the tab selection before pressing a key) |
| Visual QA | Overview, Instrument, Portfolio, Settings, transaction dialog at 1440 px; Overview and Watchlists at 390 px; Overview in light theme; no horizontal overflow, no console errors (`docs/screenshots/overview-*.png`, `instrument-1440.png`) |

## Terminal T5, movers, density and quote-page tools (11 Nov 2026)
- **T5 News tab** (`GET /api/terminal/news`, `services/news_stream.py`, provider `news()`): SEC filings with 8-K items in
  plain words, plus provider headlines (title, publisher, time, link — no article text), de-duplicated, grouped by
  day, filterable (headlines / releases / filings / key events), cited-AI entry point. Codes CN (stream) and FIL
  (filings list). Sample mode: headlines written from the fictitious dataset's dividends and results, no links.
- **Movers** (`GET /api/terminal/movers`, `/movers`, code MOV, g v): breadth, gainers, losers, most active, unusual
  volume (completed sessions only). **Terminal density** preset in Settings.
- **Chart**: indicators (SMA/EMA/Bollinger overlays, RSI and MACD panes) and CSV download of the daily table.
- **Performance overview** (`GET /api/terminal/performance`): 1W–5Y and YTD price return vs the benchmark, 52-week range.
- **Schema:** none (news cached in the market cache; density value widened in the API schema only).

| Check | Result |
| --- | --- |
| pytest SQLite | 333 passed, 3 skipped (new: T5 6 — both yfinance news shapes, unsafe links dropped, cache round trip, 8-K labels, de-duplication, fake-SEC stream, API; T9 3; performance overview 3) |
| tsc, `eslint .`, vitest | clean; 45 (indicators: SMA/EMA/Bollinger/RSI/MACD hand vectors) |
| Playwright | 34 journeys pass (new: news, movers + terminal density, quote-page extras) |

**Live check after deploying 722a48c (11 Nov 2026), read-only.** AAPL news: 80 SEC items (47 filings, 33 releases),
newest first with plain 8-K captions (e.g. 2 Nov 2026 "Results of operations (earnings release)"); Yahoo headlines
failed (ticker news endpoint refused) → search-news fallback added (DECISIONS #58). RELIANCE.NS: the gating note only.
Movers over the owner's 4 watchlisted listings: 1 up, 3 down; NVDA −5.47%; unusual volume NVDA 4.83×, DOX 3.25×.
Performance: AAPL to 10 Nov 2026 vs S&P 500 — YTD +28.2% vs +9.9%, 1Y +29.4% vs +10.1%, 3Y +87.0% vs +70.3% (5Y
was "—" because Yahoo's 5Y daily history starts a few days after the five-year mark; it now uses the first close
within a week of the mark and shows that date); RELIANCE.NS vs Nifty — 1Y −10.4% vs −1.8%.

**Live check after deploying 29d2b94.** AAPL news: 26 Yahoo headlines via the search fallback plus 80 SEC items; but
search results included stories about other companies (Nvidia, Bullish) → headlines are now kept only when Yahoo
tags them with the symbol (untagged items kept). Converter: 1,000 USD → ₹93,918.00 (USDINR=X); 100 GBP → ¥21,185;
but ₹50,000 → €475.00 because Yahoo quotes INR→EUR to 4 decimals (0.0095) → rates below 0.1 now come from the
reverse pair (EURINR=X), inverted. All twelve new watchboard series returned "available". AAPL 5Y now shows +135.7%
(18.7% a year) from 11 Nov 2021 vs the S&P 500's +61.8%.

**Re-check after deploying 69c7800.** Converter: ₹50,000 → €476.68 from EURINR=X inverted (was €475.00). AAPL
headlines still include stories Yahoo tags with AAPL but that are about other companies (Netflix, Nvidia), so the
related-ticker filter does not remove them; the stream now says so in its source line. Known limitation: no
reliable per-company relevance signal in Yahoo's search news.

## World markets and currency converter (11 Nov 2026)
Macro watchboard: world indices, more FX, silver, natural gas, crypto. Currency converter panel on Macro
(`GET /api/terminal/convert`). Yahoo headlines fall back to the search API. No schema change.

## Weekly/monthly bars, earnings bars, tab keys (11 Nov 2026)
- Chart and price table get a D/W/M interval: weekly and monthly bars aggregate the validated daily bars (first open,
  high, low, last close, summed volume; a period with any session missing OHLC or volume shows it as missing), the
  table gains a change column, and the CSV follows the interval (`lib/resample.ts`, 3 unit tests).
- Earnings history shows revenue and net income as paired bars above the table (losses in red).
- `[` / `]` step through the instrument tabs (listed in shortcut help).
- Checks: vitest 48; Playwright 35 journeys pass; no backend change.

## Watchlist key figures (11 Nov 2026)
`GET /api/watchlists/{id}/metrics` returns market cap, trailing P/E, distance from the 52-week high and 1-year return
for each member from the stored screening snapshots only (no provider call on a watchlist view, per CLAUDE.md §7);
members not loaded yet return null and the table explains how to load them. The full watchlist table shows these
on wide screens (market cap, P/E and 1Y from 1280 px, the 52-week bar from 1536 px). Checks: pytest 336, vitest 48,
Playwright 36.

## Desk: linked panels (11 Nov 2026)
`/desk` (code DESK, g d): one linked symbol drives four panels chosen per slot (chart, news, performance, events,
earnings history); layout remembered per browser (DECISIONS #59). T9 complete. Checks: vitest 48; Playwright 37.

## Dividend summary (11 Nov 2026)
`GET /api/terminal/dividends` and a Dividends panel on the Events tab: trailing-12-month dividends per share and
yield (on the latest quote), frequency from the last two years, calendar-year totals (current year marked as year to
date), 5-year growth on complete years only, consecutive yearly increases. Provider amounts per share, no forecast.
Checks: pytest 339, vitest 48, Playwright 37.

**Live check after deploying 898e301.** Dividends: AAPL quarterly, 5-year growth 5.0% a year (2020–2025), 13 yearly
increases; RELIANCE.NS annual, ₹6.00 last on 5 Jun 2026; SMR "no dividends". AAPL's trailing-12-month figure was
$0.80 (three payments) because the November 2025 ex-date fell a day outside the 365-day window and the November 2026
one was not yet reported → an "indicated annual" figure (latest payment × payments a year) and the TTM payment count
are now shown. Watchlist key figures loaded and fresh for the owner's list (e.g. NVDA P/E 22.59, −30.6% from the
52-week high).

## Terminal T3, T7, T10 (11 Nov 2026)
- **T3 Holders tab** (code HDS, `GET /api/terminal/ownership`): ownership breakdown and top institutional/fund
  holders (Yahoo, unofficial; fictitious in fixture mode), US insider transactions from Form 4 XML with codes in
  words and 90-day/12-month open-market buy/sale summaries. India: the exchange shareholding pattern stays gated.
- **T7 Options tab** (code OMON, `GET /api/terminal/options`): one expiry at a time, calls|strike|puts with last,
  bid–ask, volume, open interest (bars) and IV; put/call ratios, max pain, ATM IV and the smile. Yahoo, read-only,
  delayed; NSE F&O gated; fictitious Black–Scholes chain in fixture mode.
- **T10 Relations tab** (code SPLC, `GET /api/terminal/relationships`): customer-concentration and
  supplier-dependence sentences quoted from the latest annual report, low confidence, with a journal note button.
- **Schema:** none (holders, chains and Form 4/10-K scans live in the market cache).
- Checks: pytest 351 passed; vitest 48; Playwright 40 journeys (new: holders, options, relations).
- Live data for these three is checked after deploy (Yahoo holders and chains cannot be reached from the sandbox).

**Live check after deploying f99e9fa.** AAPL insiders: 25 Form 4 filings read, none failed; 32 open-market sales in
90 days (≈$96.6M), e.g. the general counsel's 2,399-share sales. Relations: NVDA 11 customer sentences ("one direct
customer represented 22% of total revenue…"), 3 supplier sentences; AAPL 10-K of 3 Nov 2026. Yahoo holders: HTTP
401 for AAPL and RELIANCE.NS from the server; Yahoo option expiries: none returned — both panels explain this.

## Terminal T8 (11 Nov 2026)
Market context strip on the Description tab (`GET /api/terminal/context`); US official statistics and release
calendar on Macro (`GET /api/macro/official`, FRED, needs `FRED_API_KEY`). DECISIONS #63–64. Checks: pytest 358,
vitest 48, Playwright 41 (one regression found and fixed: the context table widened the page at 360 px).

**FRED live (owner set FRED_API_KEY on Render, 11 Nov 2026).** All ten series load with dates and vintages, e.g.
CPI-U Oct 2026 = 337.476 (+4.08% y/y, revised 11 Nov), unemployment 4.1% (−0.1 pp), payrolls +165k, effective fed
funds 3.88%, 10-year 4.88%, 10y–2y +0.25 pp, real GDP Q3 +2.07% y/y, Michigan sentiment 48.1. The release calendar
listed "FOMC Press Release" every day (FRED schedules it daily); releases with more than six dates in the 45-day
window are now dropped, leaving PPI, retail sales, CPI and similar.

**Incident: Risk tab HTTP 500 for US listings (11 Nov 2026).** Once FINRA credentials were set in production, the
short-interest cache write used the kind "finra_short_interest" (20 characters) in `market_cache.kind`
VARCHAR(16): SQLite accepted it, PostgreSQL raised DataError and the whole risk view failed. Fixed: kind "finra_si",
rollback on a failed cache write, each risk section now reports its own failure instead of failing the view, and a
regression test writes the cache (CI runs it on PostgreSQL). Indian listings were unaffected (no FINRA call).

**FINRA short interest live (11 Nov 2026).** After the two fixes above, the Risk tab shows the latest year: AAPL
settlement 30 Oct 2026 short 144.8M shares, 3.36 days to cover (+10.0%); SMR 97.2M, 3.6 days; NVDA 279.6M, 2.8 days
(−7.3%). The first version returned FINRA's oldest records (AAPL from 2020) because no date filter was sent.

## Known limitations carried forward
- Market status comes from published calendars (exchange_calendars); India data ends 2026-12-31 (later dates show "unknown") and special sessions are not modelled.
- Render Free sleeps after 15 minutes idle; alerts are only evaluated while it is awake.
- Yahoo (yfinance) is unofficial; it refuses `quoteSummary` from Render, so some fundamentals are derived and labeled.
- Portfolio has INR and USD accounts; returns (M09) use daily closes, benchmarks are price indices, and cash earns no interest.

## Next concrete action
The roadmap (M00–M14) is complete, including M04 (Alpaca IEX streaming). Terminal roadmap T1–T10 is done; live inputs configured: SEC, FINRA, FRED, Groq. US option chains now come from Alpaca's indicative feed. Not available from the hosted server: Yahoo holders (Yahoo refuses the requests). India's shareholding pattern needs a permitted source.

### Live check — Alpaca option chains and IEX streaming (11 Nov 2026, US session open)
- `/api/terminal/options`: AAPL 24 expiries, default 13 Nov (first after today), 82 calls, put/call OI 1.12, max pain 345,
  ATM IV 25.6% at 355, open interest dated 9 Nov; SPY 35 expiries. Source shown as "Alpaca indicative options feed
  (delayed; not OPRA)". RELIANCE.NS still says Indian F&O is not fetched.
- `/api/stream/quotes` from the browser: status `live`, AAPL/MSFT IEX trades arriving within seconds; RELIANCE.NS
  reported as polled. Instrument header shows "IEX live · HH:MM:SS" (New York time) and "Last IEX trade"; the watchlist
  marks the streamed US rows, Indian rows keep their Yahoo freshness badge, and the feed line reads "IEX (Alpaca) —
  single exchange, not consolidated".
- Local runs: pytest 366 passed / 3 skipped; vitest 53; Playwright journeys 41/41 (one first failed only because
  the shell's real FRED key reached the local e2e server; scripts/e2e-server.sh now unsets real keys).

### Live check — Holders and Relations fixed; Alpaca news and US movers (11 Nov 2026)
- Holders (owner reported "not working": Yahoo returns HTTP 401 to this server for every symbol). Now from SEC:
  AAPL Vanguard Capital Management 7.48% (13G, 31 Mar 2026); SMR VanEck 8.50%, BlackRock 6.50%, Vanguard 5.25% plus
  holders that reported falling below 5%; NVDA no longer lists NVIDIA's own 13G about another company. Insider
  holdings from Form 4 shown. Indian listings say no permitted shareholding source exists yet. No overflow at 390px.
- Relations: AAPL now quotes its single/limited-source and outsourcing-partner dependence (was empty) and the trade
  receivables concentration; repeated quotes merged (`sec:relations:v4`).
- News (AAPL): Benzinga headlines via Alpaca tagged with the symbol; a market-wide story is marked "broad".
- Movers: "US market — all listings" (gainers, losers, most active) from Alpaca's screener, ≥ $5 common tickers.
- Instrument header: pre-market / after-hours IEX trade on its own line (unit-tested; appears outside 09:30–16:00 ET).
- Local: pytest 373 passed / 3 skipped; vitest 55; affected Playwright journeys pass.
