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
