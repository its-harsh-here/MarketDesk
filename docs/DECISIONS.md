# Decisions

Consequential choices, newest last. Routine choices live in code comments.

1. **Dependency majors.** Newer majors exist on npm (Vite 8, TypeScript 7, React Router 8, Vitest 5). I pinned the latest
   releases of majors whose APIs could be verified against installed type definitions: Vite 7.3, TypeScript 5.9,
   React Router 7.18, Vitest 3.2 (Vitest 4.1's peer set triggers an npm 10 arborist crash, `Cannot read properties of null (reading 'edgesOut')`), Zod 4, @hookform/resolvers 5. Python uses current stable releases (FastAPI 0.162,
   SQLAlchemy 2.1, Pydantic 2.14, yfinance 1.7, pandas 3.1). `@playwright/test` is pinned to 1.63.0 to match the
   pre-installed Chromium.
2. **Exact decimals in SQLite.** SQLite turns NUMERIC into REAL, so money and quantities use a `DecimalText`
   column type (TEXT on SQLite, NUMERIC on PostgreSQL). API JSON serializes decimals as strings.
3. **Currency precision.** INR has 2 decimal places. Every cash movement settles to paise (ROUND_HALF_UP) at the
   transaction; cost basis and average cost keep full precision and are rounded only for display. Input limits:
   quantity 6 dp, price 4 dp, amounts and fees 2 dp.
4. **Ledger ordering.** Replay order is effective date, then intra-day priority (deposit, split, dividend, trades,
   withdrawal), then entry order. This lets a same-day deposit fund a same-day buy without timestamps.
5. **Splits.** Only an explicit, confirmed SPLIT transaction changes quantity; trades are entered with their original
   quantities. CSV SPLIT rows count as confirmation because the owner authored the file.
6. **Dividends** require the instrument to have been held on or before the dividend date, and are tracked separately
   from realized trading P&L.
7. **Fixture namespace.** Fictitious companies use `SX:` symbols on an imaginary `SAMPLEX` exchange. The dataset is
   fixed at base date 2026-06-30 with five replay sessions (2026-07-01..07). A replay cursor and an outage switch are
   stored in the database so web and worker processes agree; the endpoints exist only in fixture mode and are
   writes (blocked in the public demo). Timestamps stay at the dataset's session close (15:30 IST), never "now".
8. **Yahoo quote construction.** One `Ticker.history(period="3mo", auto_adjust=False)` call per symbol provides the
   regular-market price/time (from `history_metadata`), the previous session close and the 3-month sparkline from the
   same series, so last price and previous close share an adjustment basis. Yahoo's chart endpoint is per-symbol, so
   "batching" means one API request for many symbols, fetched concurrently with a bound of 4.
9. **Dividend yield units.** yfinance 1.7 returned `dividendYield` in percent points (6.02 for ITC.NS on 2026-11-03)
   while `trailingAnnualDividendYield` was 0. The unit is cross-checked against `dividendRate ÷ price`; unverifiable
   values are withheld.
10. **Market status.** No verified NSE holiday/session calendar is bundled, so Yahoo mode always says
    "Market status unavailable". Fixture mode says it is a sample dataset with no live session.
11. **Allocation chart.** A plain HTML/CSS bar list with a table alternative is sufficient, so Recharts is not added.
12. **Sessions.** Server-side sessions; only an HMAC (keyed by `SESSION_SECRET`) of the cookie token is stored, so a
    database copy cannot be replayed as a cookie and rotating the secret signs everyone out. Per-session CSRF token in
    `X-CSRF-Token`, plus an Origin/Referer host check. Cookies are HttpOnly, SameSite=Lax, Secure in production.
13. **CSV import is all-or-nothing.** Any row error blocks the import; duplicates (fingerprint of normalized fields
    including notes) are skipped and shown. Confirmation uses a single-use preview token, so a double submit cannot
    import twice.
14. **Single ledger writer.** Ledger writes are serialized by a process lock around validate-and-commit. Run one web
    process (the default compose setup) for a personal install.
15. **Alert identity.** Observations are unique per (instrument, provider, market timestamp); events are unique per
    `"<alert_id>:<arm_seq>"`. Re-reading a cached quote or restarting the worker cannot create a second event.
16. **Briefing volume comparison** is not implemented: Yahoo does not reliably state whether the latest daily bar is
    complete, and the specification forbids unlabeled comparisons of incomplete sessions.
17. **Journal text** is stored and rendered as plain text (no Markdown), which removes an XSS surface.
18. **Lucide 1.x icon names.** `Trash2` and `Filter` do not exist in lucide-react 1.66; `Trash` and `Funnel` are used.
19. **Overview layout.** At ≥1280px the chart takes 8 columns and the watchlist 4 (compact columns, freshness dot next
    to the price); below that the panels stack and the watchlist shows its full columns.
20. **E2E package.** `tests/e2e` is its own small npm package (pinned `@playwright/test` 1.63.0, matching the
    pre-installed Chromium) so the suggested root-level layout works without a workspace setup. It runs against the
    production build served by FastAPI plus the real worker (`scripts/e2e-server.sh`, poll every 2 s).
21. **Docker build behind proxies.** Base images are build arguments (a registry mirror can be used when Docker Hub
    rate-limits), and an optional `ca_bundle` BuildKit secret lets the build trust a TLS-intercepting proxy without
    baking the certificate into the image. Inside the image the CLI runs as `python -m marketdesk.cli`.
22. **Security headers.** The API sets CSP (`script-src 'self'` plus the hash of the inline theme bootstrap, computed
    at build time into `dist/csp-hash.txt`), `X-Frame-Options: DENY`, `nosniff` and `Referrer-Policy`; API responses
    are `Cache-Control: no-store`; OpenAPI docs are disabled in production.
23. **Real data only (owner directive, 2026-11-03).** The product shows only real market data. Yahoo is the default
    provider; `DATA_PROVIDER=fixture` is kept solely as a deterministic test harness (pytest, Playwright, CI) and the
    server refuses to start with it in production. Removed: the public read-only demo (it existed to show synthetic
    data publicly), the sample-portfolio endpoint and button, and `marketdesk seed-demo`. This overrides the
    fixture-mode showcase described in CLAUDE.md §3. Committed screenshots are real-data captures; synthetic visual-QA
    captures go to a git-ignored folder. Deleting the harness entirely would make CI depend on Yahoo being reachable.
24. **Single-container mode.** Render disks and Fly volumes attach to one instance, so `python -m marketdesk.serve`
    validates settings, migrates (in a short-lived subprocess) and supervises web + worker in one container sharing
    the SQLite file. Measured RSS: web ≈ 171 MB, worker ≈ 130 MB, supervisor ≈ 13 MB.
25. **Entrypoint privilege drop.** The image no longer sets `USER`; `python -m marketdesk.entrypoint` chowns
    `DATA_DIR` (platform disks mount root-owned) and drops to uid 10001 before exec. The CLI does the same when run as
    root inside the image, so operator commands cannot leave root-owned files on the volume.
26. **Self-migrating startup (fix for the first Render deploy).** The live service ran the image's old default command
    (web only), so no migration ran and sign-in failed with a 500 on missing tables. Now the image's default command is
    `python -m marketdesk.serve` (migrate + web + worker), and the web app and worker both call `ensure_migrated` on
    startup (no-op at head, serialised by a file lock in `DATA_DIR`, revision re-checked under the lock). Database
    errors return an explicit 503 `database_unavailable` instead of an anonymous 500. Compose names its web command
    explicitly so it never starts a second worker.
27. **Signed session cookies (owner request: stay signed in).** Sessions were database rows, so a database reset
    (a platform restart without a persistent disk) signed the owner out. The cookie is now an HMAC-signed token
    (`SESSION_SECRET`) carrying user, issue/expiry times, session id and CSRF token, valid for 90 days and renewed
    daily while used (sliding). Sign-out revokes the session id server-side; `marketdesk revoke-sessions` sets a
    revocation epoch; rotating `SESSION_SECRET` or `OWNER_USERNAME` invalidates every cookie. The old
    `auth_sessions` table is no longer used (left in place; no destructive migration).
28. **Fundamentals without Yahoo's company summary.** Render's IPs are refused by `quoteSummary` (crumb required). On
    refusal the provider derives fundamentals from endpoints that still work: chart metadata/history (52-week range,
    trailing-12-month dividend yield), valuation measures (market cap, trailing P/E, P/B), income statements
    (statement dates) and search (sector/industry); each derived field is labelled. The refused endpoint is skipped
    for an hour instead of being retried on every request.
29. **Circuit breakers per endpoint family, transient errors only.** Separate breakers for prices, fundamentals and
    search; only retryable failures (timeouts, 429, 5xx, network) count. Yahoo answers unknown symbols with 401/404
    depending on crumb state, so those must never pause quotes. A "not found" error body maps to `missing`.
30. **Storage check.** `/api/status` reports whether `DATA_DIR` is on a mounted disk; production shows a warning on
    Overview and Settings when it is not, because container hosts discard unmounted files on restart.
31. **Symbol picker.** Results are selectable only once they match the current text; Enter during a search picks the
    top result when it arrives. Bare names that fail (e.g. `RELIANCE`) get a server suggestion (`RELIANCE.NS`) with a
    one-click fix in the Add symbol dialog.
32. **No `VOLUME` in the image; mountinfo-based persistence check.** Live testing showed data vanishing across Render
    restarts while the storage check reported "persistent": Docker satisfied the image's `VOLUME ["/data"]` with an
    anonymous volume, which is a mount point but is discarded with the container. The instruction is removed, and
    the check reads `/proc/self/mountinfo`, treating anonymous volumes (64-hex names) and tmpfs as not persistent.
    `/api/status` also reports when the database was first created, so a reset is visible in Settings.
33. **PostgreSQL support for free hosting (owner request: no paid services).** Render's Free plan has no disk, so the
    supported free setup is Render Free + an external free Postgres (Neon). `DATABASE_URL` accepts plain
    `postgres://` URLs (normalised to the bundled psycopg 3 driver); the engine uses pre-ping, recycling and a small
    pool because free Postgres suspends idle compute. The whole pytest suite runs against PostgreSQL 17 when
    `TEST_DATABASE_URL` is set (CI job `api-postgres`), `alembic check` passes on both databases, and Postgres
    missing-table errors map to the same 503 as SQLite. This supersedes CLAUDE.md §4's "no untested second
    deployment" because it is now tested. `render.yaml` targets the Free plan with `DATABASE_URL` and no disk.
34. **Performance on a free instance with a remote database (owner report: "the site became slow").** Measured live:
    every database-backed request took ~1.1 s (health 0.25–0.4 s), consistent with ~120 ms per database round trip
    and ~7 round trips per request, and async handlers ran their synchronous SQLAlchemy calls on the server's event
    loop, so a page's parallel requests were served one after another. Changes: (a) async handlers that use the
    database run on a private event loop in a worker thread (`marketdesk.asyncbridge.off_event_loop`), while market
    data calls are forwarded to the server loop that owns the cache, de-duplication and breakers; the persisted
    cache is read and written in threads. (b) Fewer round trips: pooled connections are pinged only after 30 s idle
    instead of on every checkout; GET requests on PostgreSQL use autocommit (READ COMMITTED already gives each
    statement its own snapshot, so this only drops BEGIN/ROLLBACK); session-revocation state is cached per process
    for 15 s (sign-out in the process clears it at once; `revoke-sessions` from the CLI applies within 15 s);
    preferences are read once per request; journal facets use one query. (c) A 10+10 connection pool so parallel
    requests (each may open a second short session for the market cache) never wait on each other. (d) Startup:
    yfinance is imported lazily (and warmed in a background thread), the argon2 dummy hash is computed on first use,
    `serve` no longer runs a separate pre-start process and starts the worker 45 s after the site answers at nice 10.
    (e) The browser polls alert events at the worker's sampling interval (10–60 s) instead of every 10 s and reuses
    results younger than 15 s across pages. `/api/status` reports the database round-trip time so a region mismatch
    is visible in Settings; `Server-Timing` headers expose per-request timings.
35. **M00 diagnostics and backups (owner report: "Unexpected server error" at sign-in).** The message only comes from
    the API's catch-all 500 handler; a production-like reproduction (production mode, HTTPS-terminating proxy with
    forwarded headers, SQLite and PostgreSQL, synthetic credentials) produced no 500 for any input, and the live
    service accepted the owner's credentials on 3 Nov 2026, so the original exception is only recorded in Render's
    logs from that time. Changes: every response carries `X-Request-ID` (a well-formed upstream ID is reused), error
    bodies repeat it, failures and sign-in outcomes are logged with it (never credentials, bodies or cookies); the
    sign-in screen separates wrong credentials, rate limiting, unavailable host/database, network failure and server
    errors (with the reference); pasted whitespace around `OWNER_USERNAME`/`OWNER_PASSWORD_HASH` is ignored and a
    quoted, `$$`-escaped, cut-off, non-argon2 or memory-heavy hash is refused at start-up with a specific message; the
    worker validates only what it uses. Backups: a database-agnostic logical JSON export/import (consistent snapshot,
    checksum, schema revision, restore only into an empty database in one transaction, sequence reset on
    PostgreSQL), because Render Free has no shell or disk and `pg_dump` would have to match the server version.
36. **M01 listing identity and calendars.** An instrument is a listing (venue + symbol), not a company: INFY.NS and the
    INFY ADR stay separate rows with their own currency, calendar and, later, facts. Venue identity (MIC, country)
    comes from the provider's exchange code via a reviewed mapping, is marked verified only from quote metadata, and
    unknown venues stay unknown. Provider/registry identifiers live in `instrument_identifiers` (unique per
    instrument and scheme, looked up by scheme+value because e.g. a CIK spans share classes). Session states use
    `exchange_calendars` (XNYS for NYSE/Nasdaq/Arca, XBOM for NSE/BSE) with "unknown" for dates outside its data and
    for special sessions it does not model. Comparisons align on dates where every instrument traded and are labelled
    as own-currency price returns without dividends. Backups restore across schema revisions by building the backup's
    revision first and migrating forward.
37. **M02 research data.** SEC EDGAR is the source for US registrants' filings and XBRL facts; it needs no key but a
    User-Agent with a real contact, so the adapter refuses to send requests until the owner sets `SEC_USER_AGENT`
    (no contact address is invented). Statements are normalized by explicit tag lists with full provenance, never
    mixing year-to-date with quarterly values or currencies, never deriving Q4, and leaving industrial lines unmapped
    for banks/insurers. Non-US listings show "not applicable" instead of borrowing another listing's facts. Cached
    payloads reuse the market cache table; check history lives in `research_checks`.
38. **M05 alert rules, delivery and briefings.** Crossing alerts need two observations on opposite sides (the first
    after arming is a baseline), so a level already passed when the alert is created does not fire. Volume and
    volatility rules use only sessions the exchange calendar says have finished; an unknown state counts as
    unfinished. Every event has a unique key and one delivery row per channel, written with the cooldown state in a
    single transaction; only the in-app channel exists, and a failing channel is recorded rather than retried
    silently. Quiet hours hold the notice, never the event. Briefings are stored rows, unique per kind, market and
    session date, timed by exchange calendars rather than clock rules, and are not produced from the historical sample
    dataset (a fixture-only endpoint writes one for tests). Backup restore inserts only the columns a backup contains,
    so older backups restore into their own revision and migrate forward.
39. **M08 accounts and FX.** An account is identified by its currency (INR, USD) using the ledger's existing
    `currency` column, so no existing row changes and no account table has to be seeded or backed up. An FX conversion
    is one row with two legs (paying and receiving) so it cannot be half-recorded; its rate is stored in the market
    convention for the pair (USD/INR, INR per USD) whichever way money moved, is optional, and must agree with the
    amounts. Conversions are transfers, not contributions. Valuation in a base currency is display-only, uses the
    current rate with its source and time, is withheld when a rate or a price is missing, and never feeds back into
    transactions; consolidated returns would need historical FX and are not computed. New fingerprint parts apply only
    to FX rows so duplicate detection of existing rows is unchanged.
40. **M10 decision journal.** The journal entry row is the current view; history lives in append-only
    `journal_versions` and `journal_reviews` tables that the API never updates. Only thesis fields are versioned, so
    re-tagging or rescheduling a review does not demand a change note, while any change to what was believed does. The
    instrument is fixed for the life of a note because every snapshot refers to it. Evidence is captured server-side
    from the same providers the app uses (quote, fundamentals, SEC filings) with their statuses, so a snapshot shows
    what was known and how fresh it was; comparisons fetch "now" without storing it. Existing notes are backfilled as
    version 1 explicitly marked as having no evidence rather than being given today's data. The optional Grok
    counterargument is deferred to M03 (needs a key).
41. **M03 Grok analyst on limited credit.** Evidence is retrieved and computed by MarketDesk before the model is called,
    so most answers need one model call and the model never supplies figures; a single read-only tool can read filings
    already in the evidence. Citations are checked in code (unknown ids, unsupported facts, figures absent from the
    cited sources, advice wording) instead of trusting the model's own citations. The daily budget is enforced by
    reserving a worst-case estimate before each call (serialized, PostgreSQL advisory lock) and reconciling with xAI's
    reported cost; the same request on unchanged evidence reuses the saved answer. The owner's key name `GROK_API` is
    honoured (with `XAI_API_KEY` as an alias); a configured key is the opt-in and `GROK_ENABLED=false` the off switch.
    Default model `grok-4.3` for cost; `grok-4.7` is one setting away. Only public data and the question leave the
    server; web/X search stay off.
42. **Groq's free tier as the AI provider (owner decision, 4 Nov 2026).** The owner's key in `GROK_API` turned out to be
    a Groq key (groq.com, a different company from xAI) and the owner chose Groq's free tier. The analyst keeps one
    evidence pipeline and chooses the client from the key prefix (`gsk_` Groq, `xai-` xAI; `AI_PROVIDER` overrides).
    On Groq: `openai/gpt-oss-120b` (strict json_schema), reasoning effort low with reasoning text omitted, one call per
    answer because Groq does not combine structured output with tool use, evidence trimmed deterministically (source
    ids unchanged) so a request stays under the free tier's 8,000 tokens per minute, and a daily token allowance below
    its 200,000 tokens per day. Free-tier usage is recorded with tokens and $0 cost.
43. **Screener reads a stored snapshot of a declared universe (M06, 4 Nov 2026).** A universe is a watchlist, all
    watchlists, current holdings or a pasted list (≤ 150 symbols, each verified with the provider); indices and
    currencies are left out and listed. Each member's snapshot (`screen_metrics`, rebuildable, excluded from backups)
    holds every metric as a decimal string or null with the reason, its as-of date and input provenance; screens never
    call the provider. Statement ratios use Yahoo's annual statements (`get_income_stmt`/`get_balance_sheet`, which work
    from cloud servers) and only ratios within one statement set, because the endpoint does not report the statement
    currency. Debt/equity is withheld for financial-services companies. Currency filters compare other-currency listings
    at the current USD/INR rate (stated), never by relabelling. Peer suggestions come only from instruments the owner
    already tracks (same industry, then sector, nearest market cap); chosen peer groups are owner data and backed up.
44. **Performance and risk methods (M09, 4 Nov 2026).** Daily value = cash + end-of-day quantity × as-traded close; the
    provider's split-adjusted closes are restored with its split history and recorded SPLIT entries change quantity,
    so splits count once (unrecorded provider splits are flagged). Holiday gaps carry a close forward ≤ 10 days, else
    the day is left out and its flows move forward. Time-weighted return with flows at the end of their day;
    money-weighted XIRR (365-day years); annualization only for ≥ 365 days; volatility only with ≥ 60 returns. The
    consolidated view converts USD daily at the USD/INR close and treats FX conversions as internal. Beta/correlation
    to the benchmark only when every holding shares the benchmark's exchange time zone; pairwise correlations use
    daily returns on common dates within a time zone and weekly (Friday) returns across time zones, with minimum
    sample sizes. Benchmarks are price indices (dividends excluded, stated). Rebalancing is a simulation only, with
    targets stored per account (`allocation_targets`, owner data).
45. **Valuation lab methods (M11, 4 Nov 2026).** Equity DCF on free cash flow approximated as operating cash flow −
    capex (after interest and tax; assumes no net borrowing), discounted at a cost of equity, so no debt is subtracted;
    Gordon terminal value; rejected inputs: r outside 1–40%, g outside −50–100%, g_T outside −5–10% or within 0.5 pp of
    r, N outside 1–15, base FCF ≤ 0, shares ≤ 0. Not applied to financial-services companies. Defaults show their
    source; cost-of-equity defaults (INR 12%, USD 9%) and terminal growth (4%, 2.5%) are labelled assumptions. Annual
    statements gained operating cash flow, capex and cash (Yahoo cash-flow statement; cache entries from before stay
    readable). Peer multiples use the M06 peer group and snapshots. Stress tests apply instantaneous shocks to current
    marks. Saved scenarios (`valuation_scenarios`) are owner data and backed up.
46. **Earnings dates are estimates or deadlines, never announcements (M07, 4 Nov 2026).** Without a verified, permitted
    calendar or consensus source, MarketDesk shows past results dates from SEC 8-K Item 2.02 filings, a US next date
    estimated from the median gap of past results filings (only when it looks quarterly, ±7 days), and for Indian
    listings the SEBI LODR 33(3) deadline. Earnings "surprises" are not computed. Period changes use SEC quarterly
    facts (three-month durations; year-to-date never mixed) or annual statements. Filing changes and guidance are
    deterministic quotes from the filings (Item 1A paragraph diff; guidance sentences with figures), not summaries.
    Results reminders are an alert rule (EARNINGS) evaluated by the worker, one event per date.
47. **Macro context from market-traded series only, until official sources are verified (M12, 4 Nov 2026).** The
    watchboard uses Yahoo quotes and daily history for indices, volatility indices, US Treasury yields (^TNX, ^IRX),
    FX and front-month commodity futures, labelled with provider, frequency, observation date and "not revised".
    Official statistics and release/revision calendars need a verified source with a key and licence (FRED: free key,
    attribution; RBI/MOSPI: no verified machine-readable source) and are shown as not configured. Briefings are
    deterministic (largest moves with dates) and show only owner-entered company ↔ series links; correlations are
    descriptive and use aligned observations (daily within a time zone, weekly across).
48. **Research lab: next-open execution on adjusted daily bars, fingerprinted runs, isolated paper account (M13,
    4 Nov 2026).** Rule tests use the provider's split-adjusted daily bars (open and close on one basis) and execute a
    close-time decision at the next session's open with stated slippage and fees; whole shares, long-only, no
    leverage, no interest on cash. Dividends are converted to the adjusted basis (÷ later split ratios) and credited
    when held at the prior close. Only three simple rules are offered (buy and hold, moving-average cross, momentum)
    with bounded parameters, to discourage overfitting; there is no optimiser. Each run records a SHA-256 fingerprint
    of its bars and dividends so a re-run can prove whether it saw the same data. The paper portfolio is a separate
    table set (not the ledger) replayed on read: an order fills at the first session after the latest known session at
    placement, or stays pending. Historical fundamentals are not available, so no fundamental rules exist.
49. **Workspace polish without new private storage risks (M14, 5 Nov 2026).** Workspace presets live in
    `app_settings` (no migration) and only set existing preferences. The PWA's service worker caches the shell and
    hashed assets only and never `/api`, so no authentication or data response is cached by it. The offline copy is a
    separate, opt-in, per-device snapshot in browser storage, shown only when the server is unreachable and always
    labelled with its sync time as read-only and not live; it is erased at sign-out, on any 401 and when turned off.
    Research exports are Markdown downloads (`Cache-Control: no-store`), not shareable links; private sections
    (journal, holdings) are opt-in per export and named in the file header. Owner AI quotas can only lower the
    environment caps and are applied in the same locked reservation step as the caps.
