# Status

_Last updated: 2026-11-03 — core release complete; deployment-ready (not deployed)._

## Done
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

## Checks run (2026-11-03, this environment)
| Check | Command | Result |
| --- | --- | --- |
| API tests | `cd apps/api && uv run pytest` | 64 passed |
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
- Not deployed anywhere: no hosting account was available or used.
- No licence chosen for the project's own code.

## Next (optional work, after core)
- Normalized 2–3 stock comparison chart.
- CSV mapping presets for broker exports.
- Owner action: choose a host with a persistent disk and always-on worker, create `.env`, run `docker compose up -d`,
  and put HTTPS in front (README "Production with Docker Compose").
