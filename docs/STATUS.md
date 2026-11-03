# Status

_Last updated: 2026-11-03 — real-data-only product; deployment-ready for Render or Docker Compose (not yet deployed)._

## Done
- **Real data only** (owner directive): Yahoo is the default; the synthetic fixture provider is a test harness that
  production refuses; public demo, sample portfolio and `seed-demo` removed; README screenshots are real-data
  captures (3 Nov 2026).
- **Deploy targets**: `render.yaml` blueprint (single container `python -m marketdesk.serve`, 1 GB disk, Singapore)
  and Docker Compose for any server. Entrypoint fixes disk ownership and drops to uid 10001.
- **Backend** (`apps/api`): FastAPI app factory, settings with production safety checks, SQLite WAL + busy timeout,
  Alembic migration `0001` (`alembic check` clean), models for settings, instruments, watchlists, ledger, imports,
  alerts/events, observations, journal, sessions, login attempts, persisted cache, worker status.
- **Providers**: `FixtureProvider` (committed deterministic dataset, `scripts/generate_fixtures.py`) and real
  `YahooProvider` (yfinance 1.7) behind one interface; market service with bounded memory + persisted cache, TTLs,
  de-duplication, bounded concurrency, timeouts, bounded retries with jitter, circuit breaker, stale fallback.
- **Ledger**: Decimal average-cost engine with full replay on every write; CSV preview/commit/export.
- **Alerts**: observation capture keyed by market time, unique event keys, single worker process.
- **Auth**: owner login (argon2), HMAC'd server sessions, CSRF + Origin check, login rate limit, dev bypass limited to
  development, server-enforced read-only public demo.
- **Frontend** (`apps/web`): tokens (dark + light), responsive shell (sidebar → icon rail → bottom nav), command
  palette, shortcut help, Overview, Watchlists, Instrument Detail, Portfolio, Alerts, Journal, Settings/About, login.
- **Delivery**: multi-stage `Dockerfile`, `compose.yaml` (migrate → web + worker, volume, health checks),
  `.env.example`, CI workflow, README, screenshots in `docs/screenshots`.

## Real-data/deploy checks (2026-11-03)
- Single container (`docker run … python -m marketdesk.serve`, PORT=10000, root-owned bind mount at /data): ready,
  migrations applied, all processes uid 10001, data files uid 10001, worker running, live ^NSEI/^BSESN/^NSEBANK quotes.
- `DATA_PROVIDER=fixture` with `MARKETDESK_ENV=production`: refuses to start with an explicit message.
- Compose with `.env.example` defaults (yahoo): migrate exit 0, web and worker healthy; `exec` backup as root
  produces uid 10001 files.
- Memory: web ≈ 171 MB, worker ≈ 130 MB, supervisor ≈ 13 MB.
- Render blueprint validated against Render's published JSON schema (0 errors); plan `starter`, region `singapore`.
  It has **not** been deployed: this session has no Render account access.

## Checks run (2026-11-03, this environment)
| Check | Command | Result |
| --- | --- | --- |
| API tests | `cd apps/api && uv run pytest` | 65 passed |
| API lint/format | `uv run ruff check marketdesk tests && uv run ruff format --check marketdesk tests` | clean |
| Migration drift | `alembic upgrade head && alembic check` (scratch DB) | no new operations |
| Web types/lint | `cd apps/web && npx tsc -b --noEmit && npx eslint .` | clean |
| Web unit | `npx vitest run` | 19 passed |
| Production build | `npm run build` | ok (chunks ≤ 385 kB) |
| OpenAPI types in sync | `node scripts/gen-api.mjs && git diff --exit-code src/lib/api/schema.d.ts` | in sync |
| Browser journeys | `cd tests/e2e && npx playwright test` (real API + worker, fixture mode, production build) | 10 passed, twice |
| Screenshots | `cd tests/e2e && npm run screenshots` | 27 images, no horizontal overflow at 1440/1024/390 |
| Docker image | `docker build` (via `mirror.gcr.io` base images + proxy CA secret) | built, 577 MB |
| Compose | `docker compose up` | refuses to start without credentials; with credentials migrate exits 0, web + worker healthy; login, CSRF write, deep links, JSON 404, backup verified |
| GitHub Actions CI | run #1 on `main` @ 7f6366a | API, Web, Browser journeys, Docker build: all success (https://github.com/its-harsh-here/MarketDesk/actions/runs/41588142289) |
| Live Yahoo | `cd apps/api && uv run python ../../scripts/check_yahoo.py` | search, quotes (RELIANCE/TCS/INFY/HDFCBANK/ITC.NS, ^NSEI), 1Y history, fundamentals, actions all OK |

Visual QA was done by inspecting the captured screenshots (Overview, Instrument, Portfolio, transaction dialog,
error and empty states, watchlists, alerts, light theme, palette, login). Defects found and fixed: page overflow from
`sr-only` text escaping scroll containers, empty chart area, truncated equity figure, orphan grid cell on phones,
sign wrapping away from numbers, crowded phone chart header, low-contrast amber chart line in light theme.
Token contrast was computed: all text pairs ≥ 4.5:1 in both themes.

## Live-data notes
- Yahoo was reachable through yfinance from this environment on 2026-11-03. The crumb endpoint answered HTTP 429
  (non-fatal); `Ticker.info` sometimes returned empty and sometimes full data; `marketCap` came back null for
  RELIANCE.NS on one call and is shown as missing.
- `info["dividendYield"]` is in percent points in yfinance 1.7; it is cross-checked against `dividendRate ÷ price`.
- Only RELIANCE.NS, TCS.NS, INFY.NS, HDFCBANK.NS, ITC.NS, ^NSEI (and ^BSESN, ^NSEBANK via the API) were exercised.
  Other starter symbols should work but were not individually verified.
- Yahoo-mode screenshots were inspected locally but are deliberately not committed (no redistribution of Yahoo data).

## Known limitations
- Alerts are sampled at `ALERT_POLL_SECONDS`; no email/Telegram/push channels.
- Market open/closed status is always "unavailable" (no verified NSE calendar).
- Portfolio is INR-only, long-only; no XIRR/TWR, no historical equity chart, no automatic split suggestions.
- Run a single web process: the ledger write lock and in-memory caches are per process.
- Briefing has no volume comparison (session completeness cannot be verified from Yahoo data).
- Docker Hub rate-limited pulls here (HTTP 429); README documents the mirror override.
- Not deployed anywhere yet: no hosting account was available to this session.
- Yahoo may rate-limit some cloud IP ranges; the app then shows stale/unavailable states.
- No licence chosen for the project's own code.

## Deployment
- Live URL: https://marketdesk-9vmi.onrender.com/ (deployed by the owner on Render).
- 2026-11-03 diagnosis: `/api/health` 200 but `/api/readiness` 503 and login 500 — the service ran the image's old
  web-only default command, so migrations never ran (and no worker). Fixed by the self-migrating startup (decision 26);
  verified in a Render-like container (root-owned empty disk, PORT=10000) with both the new default command and a
  web-only command: readiness ready, wrong password 401, correct password 200, writes 201.
- After commit 0411281 was deployed: live `/api/readiness` → ready; wrong-credential login → 401 (was 500);
  private API without a session → 401; SPA deep links → 200. Owner sign-in itself and the alert worker were not
  checked from here (no credentials); check Settings → Data status after signing in.

## Live QA on https://marketdesk-9vmi.onrender.com (2026-11-03, signed in as the owner)
Found and fixed (commit 08710c6, deployed):
- Fundamentals failed on every symbol ("Yahoo fundamentals request failed (HTTPError)") — Yahoo refuses its
  company-summary endpoint from Render's IPs. Now derived from Yahoo's chart, valuation-measures, statements and
  search endpoints; verified live (RELIANCE.NS: market cap ₹15,76,398 Cr, P/E 21.10×, P/B 1.74×, 52-week range,
  dividend yield, statement dates, sector/industry).
- Fundamentals failures shared the quotes circuit breaker (could pause all prices) — separate breakers, transient
  errors only.
- Adding "RELIANCE"/"ITC" failed (422): the picker offered raw text before results loaded — fixed; server now
  suggests RELIANCE.NS with a one-click fix.
- Sign-ins lost on restart — signed 90-day sliding session cookies; verified live (cookie Max-Age 90 days, reload
  stays signed in).
- Sign-in survived a live redeploy (12:06 → 12:09 UTC) with the signed cookie. A marker watchlist did **not**
  survive: the service has no persistent disk. The earlier "persistent" reading was an anonymous Docker volume
  created by the image's `VOLUME` line; fixed (decision 32). **Owner action: attach a Render disk at `/data`.**
Live journeys passing: sign-in, overview, watchlist create/add (click and quick-Enter)/delete, instrument ranges and
candles, index page, command palette, alert create/delete, journal create/delete, transaction dialog validation
(not submitted — real ledger), settings/data status, phone layouts (no overflow), reload keeps session.

## Free hosting (PostgreSQL) — in review
- Branch `claude/gifted-babbage-cg6smx`, pull request to `main` (owner reviews and merges every change from now on).
- Verified: full pytest suite on PostgreSQL 17 (84 passed, SQLite-only backup test skipped) and on SQLite (85 passed);
  `alembic check` clean on Postgres; production image with no disk + external Postgres: data, ledger and sign-in
  survived destroying and recreating the container; storage check reports external Postgres as persistent.
- Owner actions after merging: create a free Neon project, set `DATABASE_URL` on Render, switch the instance to Free.

## Next — deployment (owner chose Render)
1. Generate the password hash (README → Deploy).
2. Render dashboard → New → Blueprint → this repository, branch `main`; enter `OWNER_USERNAME` and
   `OWNER_PASSWORD_HASH` (no quotes); apply.
3. After the first deploy: open `/api/health`, sign in, load the NSE starter, and check Settings → Data status
   (provider Yahoo, worker running). Record the URL here.

## Next (optional work, after core)
- Normalized 2–3 stock comparison chart.
- CSV mapping presets for broker exports.
- Owner action: choose a host with a persistent disk and always-on worker, create `.env`, run `docker compose up -d`,
  and put HTTPS in front (README "Production with Docker Compose").
