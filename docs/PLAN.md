# MarketDesk implementation plan

Concise checklist. Status of each item lives in `docs/STATUS.md`; design decisions in `docs/DECISIONS.md`.

## Slice 1 — foundation and Overview
- [ ] Monorepo layout (`apps/api`, `apps/web`, `fixtures`, `tests/e2e`, `docs`, `scripts`)
- [ ] FastAPI app, settings (`DATA_PROVIDER`, env modes), SQLite WAL + busy timeout, Alembic migration
- [ ] Deterministic fixture generator + committed fictitious dataset (`SX:` namespace, fixed dataset date)
- [ ] `MarketDataProvider` interface, `FixtureProvider`, server cache + freshness metadata
- [ ] Design tokens (dark + light), responsive shell, sidebar/topbar/bottom nav, Sample-data badge
- [ ] Overview: market strip, chart, watchlist, briefing, journal activity, portfolio value (only with holdings)

## Slice 2 — search, chart, watchlists
- [ ] Symbol search API (name + symbol, exchange + currency), command palette (Ctrl/Cmd+K)
- [ ] Instrument detail: chart (line/candle, volume, ranges, crosshair, reset), fundamentals, corporate actions
- [ ] Watchlist CRUD, item add/remove/reorder, sort persistence, star toggle, sparklines

## Slice 3 — ledger
- [ ] Decimal ledger engine (deposit, withdrawal, buy, sell, dividend, confirmed split), replay validation
- [ ] Transactions API + dialog, holdings, cash, realized/unrealized P&L, allocation
- [ ] Canonical CSV import (preview, row errors, duplicate fingerprint, atomic confirm) + export with formula-injection defence

## Slice 4 — alerts, journal, briefing
- [ ] Alerts CRUD, arm/rearm, unique event key, in-app notifications
- [ ] Worker process: observation capture + sampled evaluation; fixture "advance session" test path
- [ ] Journal CRUD + symbol/tag filters; rule-based daily briefing

## Slice 5 — live provider, resilience, auth
- [ ] `YahooProvider` (yfinance) with normalization, timeouts, bounded concurrency, retry/backoff, circuit breaker
- [ ] Stale fallback, persisted bounded cache, fixture fault injection for outage drills
- [ ] Owner login (argon2), server sessions, CSRF, rate limiting, dev bypass (dev only), public read-only demo

## Slice 6 — delivery
- [ ] pytest suite (accounting example and all required cases), Vitest, Playwright journeys
- [ ] Screenshots 1440×900 / 1024×768 / 390×844 inspected and fixed; samples in `docs/screenshots`
- [ ] Production build served by FastAPI (SPA deep links, JSON 404 under `/api`)
- [ ] Dockerfile, compose (migrate/web/worker, volume, health checks), CI, README, `.env.example`, backup/restore

## Optional (only after core passes)
- [ ] Normalized 2–3 stock comparison
- [ ] Saved layout density (density setting is core; per-layout presets optional)
- [ ] CSV mapping presets
