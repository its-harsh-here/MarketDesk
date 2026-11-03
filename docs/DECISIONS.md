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

