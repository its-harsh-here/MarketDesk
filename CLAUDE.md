# MarketDesk — project instructions

## 1. Mission and priorities

Build MarketDesk, a polished personal market research terminal for daily use, initially focused on Indian equities. The owner wants to open it each morning, understand changes in their watchlist, inspect a company, record holdings, and track their investment reasoning. The application should feel like a serious workstation, with approachable navigation and excellent visual hierarchy.

Priorities, in order: truthful data and correct calculations; complete everyday workflows; exceptional visual execution; reliability and straightforward deployment; additional features. Deliver implemented software, not a collection of mock screens. Work within a limited Claude Code cloud-session budget. There is no paid LLM API budget, and no runtime AI dependency is needed. A single prompt starts the work but does not guarantee unlimited execution time or credit.

Read existing repository instructions and code before making changes. If the repository already has an application, preserve useful code and adapt the structure rather than deleting it. Never overwrite unrelated work. Make routine decisions yourself and record consequential decisions in docs/DECISIONS.md. Ask only for genuinely missing credentials or a decision with irreversible consequences; keep building independent functionality while blocked.

## 2. Scope and completion order

The required first release contains Overview, Watchlists, Instrument Detail, Portfolio, Alerts, Journal, and Settings. Finish the complete core before optional work. A fixed watchlist of 10–20 symbols is an appropriate starting size. This is a personal research tool: no order execution, brokerage login, investment recommendations, paid subscriptions, or multi-tenant SaaS in this release.

Ship in these vertical slices, verifying each before expanding:
1. Running application, design tokens, responsive shell, fixture provider, and Overview.
2. Symbol search, instrument chart, and persistent watchlist CRUD.
3. Transaction ledger, holdings, cash balance, and CSV import/export.
4. Persisted price alerts, journal, and rule-based daily briefing.
5. Yahoo provider, cache, failure handling, authentication, and worker.
6. Production build, deployment instructions, browser QA, and final polish.

Optional only after all required acceptance checks pass: two- or three-stock normalized price comparison; saved layout density; portfolio CSV mapping presets. Do not start options chains, stock prediction, strategy backtesting, drag-and-drop dashboard builders, full-market screeners, social feeds, or mobile native apps. Do not install an agent framework.

## 3. Product modes and truthful data

Implement MarketDataProvider with two adapters: YahooProvider using yfinance, and FixtureProvider using deterministic synthetic data committed to the repo. YahooProvider must be real code even if outbound access prevents verifying it in the coding environment. Report an unverified live integration explicitly.

Use DATA_PROVIDER=fixture|yahoo. Fixtures make all core workflows reproducible without internet or secrets. Show a persistent, tasteful "Sample data" badge and a fixed dataset date in fixture mode. Use fictitious companies for synthetic market data; keep real Yahoo symbols in a separate starter-watchlist configuration. Do not display fabricated quotations for real companies. Do not call fixture prices live, update their timestamps to the present, or silently substitute fixtures when Yahoo fails.

In Yahoo mode, distinguish loading, available, cached, stale, missing, unsupported, and upstream unavailable. Always include source, market timestamp, fetched timestamp, currency, timezone, and freshness status. Never replace missing data with zero. Display an em dash with an explanation. A recent fetch does not prove a fresh market quotation. Never imply a known exchange delay unless the feed actually supplies it.

The owner can run a private application with their own watchlists and transactions. An optional public showcase uses fixture data and read-only server endpoints; visibly explain read-only actions. Do not expose the owner's real portfolio or redistribute a live Yahoo feed publicly by default. Code licensing and underlying market-data rights are separate. yfinance is unofficial; review its documentation and linked data-use terms before public distribution.

## 4. Architecture and dependencies

Prefer a small monorepo with React + TypeScript + Vite for the frontend and Python + FastAPI for the backend. Use Tailwind CSS with CSS variables, accessible Radix/shadcn primitives where useful, Lucide icons, TanStack Query for server state, and React Hook Form + Zod for forms. Use TradingView Lightweight Charts for price charts and a small chart library such as Recharts only where needed for allocations. Use supported library APIs verified against installed versions; do not guess version-specific methods. Retain required chart-library attribution and licenses.

Use SQLAlchemy, Alembic migrations, Pydantic models, and SQLite with WAL mode for the personal installation. Persist SQLite in a mounted data directory and use short transactions and a busy timeout. Do not require Redis, Kubernetes, external auth services, or a paid database. Leave storage access clean enough to migrate to Postgres later, without implementing an untested second deployment now.

Keep frontend and backend on the same origin in production: build the SPA, serve its static assets from FastAPI, reserve /api for API routes, and support direct navigation to client routes. In development, Vite proxies /api to FastAPI. In production, missing /api routes return JSON 404s and never the SPA shell. A backend worker process handles alert evaluation; do not start duplicate schedulers in each web worker.

Suggested structure:
- apps/web/src/{app,components,features,lib,styles}
- apps/api/marketdesk/{api,config,db,models,schemas,providers,services,worker}
- apps/api/tests; apps/web/tests; tests/e2e
- fixtures; docs; scripts; .github/workflows
- README.md; .env.example; Dockerfile; compose.yaml; CLAUDE.md

Frontend features own their components and API hooks. Backend routes validate and delegate to services; providers do fetching and normalization; pure calculation modules do financial arithmetic. Generate or synchronize TypeScript API types from OpenAPI. Pin dependencies with lockfiles, choose compatible stable versions, and record actual runtime versions in the README. Keep secrets out of frontend bundles and version control.

## 5. Visual direction — specific design requirements

Create an original financial workstation with a charcoal canvas, restrained amber highlights, crisp typography, and dense but readable tables. Use Bloomberg only as inspiration for information density and keyboard speed; do not copy its branding. The main entry screen is the functional Overview, not a marketing landing page.

Use these initial design tokens, adjusting only for measured contrast:
- Canvas #0B0E14; sidebar #10151D; panels #141B25; elevated panels #1A2330.
- Borders #2A3545; primary text #EDF2F7; secondary text #A7B3C4.
- Accent #F2B84B; positive #43D3A0; negative #FF7185; informational #78AAFF.
- Use near-black text on filled amber controls. Gains/losses also need signs, arrows, or words.
- Spacing scale 4/8/12/16/24/32; panel radius 10–12px; control radius 6–8px.
- Use a readable sans face such as Inter with a system fallback; use a mono face for prices, ticker symbols, times, and aligned figures. Bundle fonts if permitted; otherwise use system fonts, avoiding network-dependent builds.
- Body text approximately 14px; table text 13–14px; captions at least 12px; primary figures 24–30px. Use tabular numerals and right-align numeric columns.

Avoid neon glows, decorative gradients, excessive glass effects, giant empty KPI cards, stock photography, emoji icons, constant ticker animation, and generic purple SaaS styling. Every chart and panel must earn its space with useful information. Keep borders subtle and use color sparingly. Create reusable Panel, Metric, DataTable, InstrumentBadge, FreshnessBadge, EmptyState, ErrorState, and Skeleton components.

Desktop at 1440px: use a roughly 208px sidebar, 64px topbar, 24px content gutters, and a 12-column grid. Topbar contains the current workspace, global symbol/command search, provider status, and a user/settings control. Navigation order: Overview, Watchlists, Portfolio, Alerts, Journal. Instrument Detail opens from search or a table. Use a compact market strip above the main grid. Give the principal chart about 8 columns and the relevant watchlist about 4; use a lower row for the briefing and recent journal activity. Keep at least the first useful chart and table visible without scrolling on a standard laptop.

At 1024px, collapse navigation and stack secondary panels. At 768px, use one main column. At 390px, use a compact header and bottom navigation for Overview, Watchlists, Portfolio, and More; transform wide tables into legible summary rows with expandable details. Never shrink everything into unreadable text. Horizontal scrolling belongs inside genuinely wide tables only, never on the whole page. Respect safe-area insets and provide touch targets around 44px.

Support dark and light themes using the same token system, persist the choice, and avoid a theme flash. If time is tight, complete and verify the dark theme first, then add the light palette without duplicating components. Respect reduced-motion settings. Use 120–180ms transitions for drawers and menus, with no decorative animation loops.

## 6. UX and interaction contracts

Global command palette opens with Ctrl/Cmd+K and accepts company names, symbols, page names, and actions such as Add transaction. Debounce remote search, cancel superseded requests, and support arrow navigation, Enter, and Escape. Do not capture shortcuts while someone types in an input. Include a discoverable shortcut hint and a shortcut-help dialog.

Clicking any instrument row opens its detail page; a visible star adds/removes it from a watchlist without navigating. A transaction dialog validates inline and preserves input on server errors. Destructive actions require confirmation or a real undo mechanism. Toasts supplement inline status; they are not the only error explanation. All visible interactive controls must function or be clearly disabled with a reason; never show success before a write completes.

Use initial skeletons matching the finished layout, preserve previous results during background refresh, and display a subtle refreshing indicator. A provider error should affect its panel rather than blanking the entire dashboard. Empty watchlists offer Add symbol; empty portfolios offer Add transaction and Import CSV. Never invent holdings to fill the owner's empty account. Offer an explicit sample workspace separately.

Use semantic landmarks, labeled inputs, associated error messages, keyboard-operable menus, focus traps and focus return for modals, visible focus rings, and screen-reader names for icon buttons. Target WCAG AA text contrast. Charts require an accessible title, date range and summary, and a table/list alternative for underlying values. Tooltip content must also be reachable by keyboard. Test zoom and long names. Keep loading, empty, invalid, stale, offline, success, and permission-denied states visually consistent.

## 7. Required screens and behavior

### Overview
Show selected market benchmarks where available, the owner's top watchlist, a selected instrument chart, and a concise daily briefing. Show portfolio value only when holdings exist. Each metric has its unit, period, and source timestamp. Let the user choose a default watchlist and chart symbol; persist those preferences.

Compute the briefing with ordinary rules and templates: largest observed moves in the watchlist, distance from user-set price thresholds, and alerts triggered. Never infer a cause from a price move or describe a stock as a buy. A volume comparison, if implemented, compares a completed daily bar with comparable complete sessions; do not compare an incomplete trading day with full-day volume without labeling that limitation. No LLM calls are necessary.

### Watchlists
Create, rename, delete, and switch watchlists; add/remove symbols; persist order or sort settings. Columns: instrument, exchange, last price, absolute and percentage change, volume if available, small historical sparkline, and freshness. Search matches by both name and symbol, and disambiguate exchange and currency. Cache recent successful search results. Keep last-price and previous-close adjustment bases consistent.

### Instrument Detail
Include company name, symbol, exchange, currency, last observed price, market timestamp, watchlist toggle, and Create alert. Chart defaults to a dependable daily-history range; offer 1M/3M/6M/1Y/5Y only where supported. Support line/candlestick, volume toggle, crosshair, date tooltip, zoom/reset, and responsive resizing. Validate date ordering, duplicate timestamps, nulls, and ascending OHLC data before rendering. Do not use randomly generated sparklines in Yahoo mode.

Fundamentals show available market cap, P/E, dividend yield, 52-week range, and financial statement dates with null-safe formatting. Preserve source units and distinguish ratios, percentages, and absolute currency. Do not fetch expensive company info on every watchlist refresh. If coverage is incomplete, make the missing fields clear rather than hiding the whole screen. News is optional; if implemented, display source headlines, dates, and original links without scraping article bodies or fabricating summaries.

### Portfolio
Implement a persistent INR ledger for DEPOSIT, WITHDRAWAL, BUY, SELL, DIVIDEND, and explicitly confirmed SPLIT adjustments. First release supports long-only INR holdings. Non-INR instruments may be researched but cannot be added to this portfolio; show why. No currency conversion by relabeling amounts.

Transactions contain effective timestamp/date, instrument when relevant, quantity, price, fees, currency, notes, and immutable creation metadata. Accept manual input and the documented canonical CSV schema. Show an import preview, row-specific errors, duplicate detection, and a confirmation before atomic import. Export transactions and holdings. Defend exported spreadsheet cells against formula injection. User-defined labels and imported content are untrusted text.

Holdings show quantity, average cost, remaining cost basis, last observed price, market value, and unrealized P&L. Show cash separately and compute total equity as cash plus marked holdings. Record realized P&L and dividends separately. Clearly label average-cost accounting as an analytical convention, not a tax report. Editing historical transactions must replay and validate the ledger; reject negative cash or overselling at any intermediate point and explain the offending row. Include fees consistently.

Use Decimal arithmetic on the backend for money and quantities; serialize decimals as strings, and round only for presentation. Define currency precision explicitly. Buy total cost is quantity × price + fees. A sell releases quantity × current average unit cost; realized P&L is proceeds minus sell fees minus released basis. Splits change quantity and average unit cost while preserving total basis, and must not also be applied a second time through adjusted transaction quantities.

Acceptance arithmetic: deposit INR 10,000; buy 10 at INR 100 with INR 10 fees; buy 10 at INR 120 with INR 10 fees. Average unit cost = INR 111, total basis = INR 2,220, cash = INR 7,780. Sell 5 at INR 130 with INR 5 fees: realized P&L = INR 90, quantity = 15, remaining basis = INR 1,665, cash = INR 8,425. At a price of INR 140, holdings value = INR 2,100, unrealized P&L = INR 435, total equity = INR 10,525. Total profit before dividends = INR 525. A subsequent 2-for-1 split produces 30 shares and INR 55.50 average cost, retaining INR 1,665 basis.

Do not call net deposits a gain. Do not equate change in portfolio value with investment return. Defer XIRR, time-weighted returns, and a historical portfolio-equity chart until correctly implemented with cash flows, corporate actions, and tests. A current allocation chart plus accurate P&L is enough for v1. If any holding lacks a usable mark, label total valuation incomplete and identify it; never silently value it at zero. Cached marks make valuation visibly stale.

### Alerts
Persist instrument, ABOVE/BELOW target, target price, active state, last evaluation, and triggered history. Evaluate in a single worker against new, valid provider observations; repeated reads of the same cached quote cannot create new events. An active alert triggers once on the first observed match, then requires rearming; document that this is sampled detection, not tick-by-tick execution. Use a unique alert-arm/event key and transactional writes to prevent duplicate events across worker restarts. No evaluation on fixture data in Yahoo mode or on stale/error responses.

In-app notifications are required. Email, Telegram, and background push are optional and must not be shown as working without configuration. Explicitly state that alerts require the server and worker to be running; sleeping hosting cannot offer uninterrupted alerts. Show last evaluation and provider health. Provide a deterministic test path that triggers an alert using the fixture provider.

### Journal and Settings
Journal entries connect a symbol to a date, thesis, risks, invalidation conditions, tags, and review date. Support create/edit/delete, symbol/tag filters, and persistence. Render plain text or safely sanitized Markdown. Do not call a user's note an AI recommendation. Settings contain theme, density, default watchlist, display timezone, data status, export/backup guidance, and a visible about/attribution page. Keep operational secrets out of UI settings.

## 8. Data-provider resilience

Provider interface should expose search, quotes, history, fundamentals, and corporate actions, with structured availability errors. Normalize exchange timezone, currency, and symbol identity once. Candidate Yahoo starter symbols include RELIANCE.NS, TCS.NS, INFY.NS, HDFCBANK.NS, ITC.NS, and ^NSEI; validate actual coverage and metadata before relying on them. Fixtures use a distinct namespace.

Cache on the server with bounded size and configurable TTLs. Suggested conservative starting values: quotes 5 minutes while actively viewed; history 1 hour; fundamentals 24 hours; symbol search 24 hours. These are product defaults, not claims about Yahoo's quotas. Deduplicate simultaneous requests and batch supported quote fetches. Back off on 429/5xx with jitter and a bounded retry count; open a temporary circuit after repeated failures. Do not rotate proxies or evade provider limits. Pause unnecessary browser polling when hidden. Limit user watchlist size and query payloads.

Execute blocking yfinance operations outside the async request loop, with bounded concurrency and request/upstream timeouts. A failed provider request may return the last known result with explicit stale metadata. Persist or bound cache storage so it cannot grow forever. Treat malformed responses as errors and log sanitized diagnostic information. Never log account passwords, session tokens, full imported portfolios, or raw secrets.

Store UTC timestamps; display Asia/Kolkata by default and preserve exchange/session dates for daily bars. Clearly distinguish daily trading dates from UTC instants. Do not label a market open based solely on weekdays and time; holidays and exchange sessions require a verified calendar. Use "Market status unavailable" when uncertain. Document raw versus adjusted prices: current position marks use current quotes, historical charts expose their adjustment basis, and corporate actions must not be counted twice.

## 9. Persistence, authentication, and API safety

Create migrations for settings, instruments, watchlists/items, ledger transactions, alerts/events, journal entries, and any persisted cache. Use foreign keys and indexes. Add mutation validation, meaningful HTTP status codes, bounded pagination, and predictable error objects. Use transactions for imports and ledger edits. An idempotency key or unique import-row fingerprint prevents accidental duplicate submissions.

Private deployment uses a single owner login configured via environment variables, a proven password-hashing library, and secure server-validated sessions. No self-service public signup. Rate-limit login attempts, avoid credential leaks, and use HttpOnly cookies with SameSite protection and Secure in HTTPS deployments. Validate request origin/CSRF tokens for cookie-authenticated mutations. Restrict CORS rather than allowing every origin with credentials. Production startup must fail if required owner credentials/session secrets are missing. Document credential rotation and session invalidation.

A development-only auth bypass must be explicitly enabled, limited to the local development setup, and rejected under production configuration. Do not create an undocumented production bypass or a default public password. Apply read-only restrictions for public fixture showcases on the server, not only disabled buttons. Validate symbols and numeric ranges, bound uploads, reject unsupported file types, and never fetch arbitrary URLs supplied by users.

## 10. Verification and UI quality gate

Use pytest for calculations, ledger replay, provider normalization, cache/error behavior, auth, and alert idempotency. Use Vitest/React Testing Library for important formatting and interaction behavior. Use Playwright for real end-to-end flows. Avoid tests that merely repeat implementation or assert that a page title exists.

Required automated cases: the accounting example above; buy/sell fees; overselling and negative-cash rejection; historical edits; split basis preservation; duplicate import; malformed CSV; decimal rounding; missing/stale prices; correct percent-versus-ratio rendering; alert fires once and can be rearmed; worker restart does not duplicate events; unauthorized private API access is denied; public-demo mutation endpoints reject writes.

Required browser journeys: search symbol → open chart → change range → add to watchlist → refresh and verify persistence; create transactions → verify holdings and cash; CSV preview → import → reject duplicate; create alert → advance fixture observation → see exactly one event; create/edit/filter journal note; change theme; open command palette using keyboard; recover from provider error while prior cached data remains visibly stale.

Run Playwright against the real app and API with fixture mode; do not mock away all backend behavior. Also smoke-test the production build and SPA deep links. Test Yahoo separately if networking permits and report that result independently of fixtures. CI must be deterministic and not depend on Yahoo being up.

Capture and actually inspect screenshots at 1440×900, 1024×768, and 390×844. Inspect Overview, Instrument Detail, Portfolio with data, transaction dialog, and an error/empty state. Fix clipping, page overflow, misaligned numbers, illegible charts, poor contrast, missing focus, and mobile menu issues. Include a few screenshots in docs/screenshots. Use Playwright directly if available; an MCP/browser integration is optional, not a required paid service. If browser execution is impossible, clearly mark visual verification as unperformed and provide the runnable command; never claim visual QA from code inspection alone.

## 11. Deployment and handoff

Provide a multi-stage Docker build, compose.yaml with web and worker services, a persistent data volume, health checks, and safe defaults. Apply migrations once through an initialization step; do not race migrations across services. Avoid destructive reseeding on startup. Document a consistent SQLite backup/restore procedure using its backup facilities rather than copying a live database file without its WAL. A restore must preserve watchlists, transactions, alerts, and journal entries.

Expose /api/health and /api/readiness without sensitive diagnostics. Include environment examples with explanatory comments, source and chart attribution, setup commands, fixture and Yahoo mode instructions, dev/build/test commands, and deployment requirements. Hosting must support the Python web process, a worker, and persistent disk. Do not assume a static-only host can run the backend or that a free tier offers persistent storage/always-on jobs. Verify current host capabilities if naming one. Document HTTPS and reverse-proxy settings.

Prepare deployment artifacts without purchasing services or exposing the owner's data. If deployment access is available and authorized, deploy and verify the actual URL. Otherwise produce a runnable build and exact deployment instructions, and describe it as deployment-ready rather than already deployed. Never invent a deployment URL or passing test result.

## 12. Working style and completion contract

At the start, inspect the repo and available runtimes, then create docs/PLAN.md with short checkboxes and proceed immediately to implementation. Keep docs/STATUS.md updated after meaningful milestones with completed work, exact commands, checks, limitations, and the next task. Use small coherent commits when repository policy permits. Do not spend the budget repeatedly rewriting plans or changing frameworks. Prefer sequential work; use extra agents only when the user explicitly authorizes them and the work is truly separable.

Work until the core release passes its acceptance criteria or a concrete external blocker prevents further progress. If credits/time become limited, preserve a fully functioning vertical slice and record incomplete features accurately. Do not replace missing features with fake buttons, stub API successes, TODO handlers, or static screenshot-like panels. Never delete failing tests simply to produce a green result.

Before the final handoff, run available lint/type checks, Python tests, frontend tests, production build, and critical browser flows. Check for tracked secrets and unused placeholder controls. Report the actual results, remaining gaps, live-data verification status, authentication/deployment setup, and where the screenshots are. Distinguish functional correctness, visual verification, and production readiness: none is established solely by generating code.

## Reference documentation

Use current official documentation and installed-version APIs rather than copying old examples:
- Claude Code project instructions: https://code.claude.com/docs/en/memory
- yfinance and data-use notice: https://ranaroussi.github.io/yfinance/
- yfinance API reference: https://ranaroussi.github.io/yfinance/reference/index.html
- Lightweight Charts and attribution: https://tradingview.github.io/lightweight-charts/docs
- FastAPI: https://fastapi.tiangolo.com/
- Vite: https://vite.dev/guide/
- Playwright: https://playwright.dev/docs/intro
