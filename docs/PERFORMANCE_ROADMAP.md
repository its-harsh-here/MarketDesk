# Performance roadmap — stay under 512 MB on Render Free, and feel faster

Written 12 Nov 2026 after two production restarts for exceeding Render Free's 512 MB memory limit. Two people use
the site. Every number below was measured in this repository, not estimated, unless marked "estimate".

## 1. What uses the memory today (measured)

The container runs three Python processes (`python -m marketdesk.serve`): a small supervisor, the web server
(uvicorn, one process), and the alert worker. Measured locally with the production entrypoint in live-data mode:

| Process | At idle | After browsing 12 companies × 11 tabs | Notes |
| --- | --- | --- | --- |
| Supervisor (`marketdesk.serve`) | 23 MB | 23 MB | Standard library only |
| Web (uvicorn) | 175 MB | **297 MB**, then **342 MB** after 6 more companies | Grows ~7–8 MB per new company and does not give memory back |
| Worker | 131 MB | 131 MB | Local run had no SEC research configured; production also processes filings, so it is likely higher there |
| **Total** | **~330 MB** | **~450–500 MB** | Plus Render's own container overhead → over 512 MB |

Where the baseline comes from (one process each):

| Import | Resident memory after import | Import time |
| --- | --- | --- |
| Python + app config | 33 MB | 1.5 s |
| pandas | 65 MB | 3.4 s |
| yfinance (pulls in pandas, numpy, requests…) | 99 MB | 3.3 s |
| exchange_calendars | 74 MB | 0.7 s |
| Worker module, fully imported | 112 MB | 1.1 s |

Why it grows:
1. **Every process pays for pandas + yfinance (~65–100 MB) separately**: web and worker each load them.
2. **In-process caches have an entry limit (1,024) but no size limit.** A 5-year daily history, statements, news,
   option chains and intraday bars are kept as Python objects per company; with ~10 kinds per company the entry cap
   is far above what fits in memory.
3. **Many threads → many malloc arenas.** Provider calls and blocking routes run on threads; glibc gives threads
   their own memory arenas and rarely returns freed memory to the system. Measured: the same browsing run peaked at
   **269 MB with `MALLOC_ARENA_MAX=2` versus 297 MB without** (−28 MB, ~10%).
4. **Large one-off payloads** (SEC company facts, filings, annual reports for relationship extraction) are read
   fully into memory; after they are freed the process keeps the space.
5. **PostgreSQL pool of 10 + 10 connections per process** — far more than two users need.

Target budget (with ~100 MB headroom for Render's overhead and spikes):

| Process | Target |
| --- | --- |
| Supervisor | ≤ 25 MB |
| Web | ≤ 230 MB steady, never above 260 MB |
| Worker | ≤ 140 MB (or 0 MB if merged into the web process — Phase 2, option A) |
| **Total** | **≤ 400 MB** |

## 2. What makes it feel slow today (measured)

| Where | Measured | Cause |
| --- | --- | --- |
| First visit after ~15 idle minutes | 30–60 s (Render's documented spin-up) | Render Free sleeps idle services; the container restarts and Python re-imports everything |
| Macro page, first load | 18 s to network idle | Many series fetched on demand from the provider |
| News tab | 1.9 s average, 2.5 s worst | Three headline sources fetched per request, then filtered |
| Description tab | 1.7 s average, 2.2 s worst | Quote, history, fundamentals and statements computed on first view |
| Peers / Earnings (first view per company) | 0.7–2.2 s | Computed on demand |
| Small shared calls (`/api/ai/status`, `/api/market/sessions`) | ~120 ms average, spikes to 1.1 s | Queued behind slow requests in the same process |
| JavaScript | 28 files, 1.29 MB raw; main bundle 397 KB (121 KB compressed) | Code-split already; main bundle still large |
| Static assets | Brotli-compressed, but hashed files have **no long-lived cache header** | Browsers re-check them on every visit |
| Visual effects | Animated aurora background, blur and glass panels | Costly on phones and low-power laptops |

## 3. Roadmap

Each step lists what to do, why, the expected effect, and how to check it. Do them in order; stop when the targets
in §1 hold for a week of normal use.

### Phase 0 — Measure in production (½ session, no behaviour change)
- [x] **0.1 Report memory in the app.** Add each process's resident memory (and peak) to `/api/system/status` and
      Settings → Data status; the worker reports its own in its heartbeat. *Check:* numbers visible on the live site.
- [x] **0.2 Log memory per request type** (in `/api/status` → `memory.routes`; not yet shown in Settings) (web): record resident memory before/after the 20 heaviest routes in a
      bounded in-memory table, so growth is attributable. *Check:* top routes by memory growth listed in Settings.
- [x] **0.3 Soak-test script in the repo** (`scripts/memory_soak.py`, standard library; passes at ≤ 300 MB web, ≤ 40 MB growth after warm-up) (`scripts/memory_soak.py` / Playwright): browse N companies × all tabs
      against a local production-mode server and fail if the total exceeds 400 MB. This is the test used for this
      document, made repeatable.

### Phase 1 — Quick wins, low risk (1 session) · expected total ≈ −90 to −140 MB
- [x] **1.1 `MALLOC_ARENA_MAX=2`** for all processes (set in `serve.py` before starting children, and in the
      Dockerfile). *Measured −28 MB on the web process.*
- [x] **1.2 Return freed memory to the system** (after growth > 4 MB, every 25 API requests, near the soft limit, and after each worker cycle): call glibc `malloc_trim(0)` after large requests and after each
      worker cycle (via `ctypes`, Linux only, no-op elsewhere). *Expect −20 to −60 MB after spikes; verify with 0.3.*
- [x] **1.3 Bound the in-memory cache by size, not just count** (150 entries; history, intraday, statements, options, holders, news and corporate actions are database-only; the option-chain client keeps ≤ 8 slimmed entries): lower `MEMORY_CACHE_ENTRIES` from 1,024 to ~150,
      and keep heavy kinds (5-year history, intraday, statements, option chains) only in the persisted database
      cache, which is already shared and survives restarts. *Expect the web process to stop growing per company.*
- [x] **1.4 Fewer threads** (one shared pool of 6 for blocking routes and `to_thread`, replacing a new pool per request; worker 4): cap the default asyncio thread pool (used by `to_thread` and blocking routes) at 4–6
      threads; provider concurrency is already 4. Two users never need 32 threads. *Fewer arenas, less memory.*
- [x] **1.5 Smaller database pool**: web 6 + 4 (a page's parallel requests can use two sessions each), worker
      2 + 1 (was 10 + 10 each). *Less client memory and fewer Neon connections.*
- [~] **1.6 Worker batch sizes**: screener refresh batch 60 → 15 per cycle (done); SEC research and relationship scans one
      company at a time with `malloc_trim` between. *Lower worker peaks.*
- [ ] **1.7 Stream large documents** (not done yet): read SEC company facts and annual reports in bounded chunks, keep only the
      fields used, and drop raw text immediately. *Removes the largest single spikes.*
- [x] **1.8 Safety valve**: if a process passes a soft limit (web 300 MB, worker 180 MB), it finishes the current
      request/cycle and exits; the supervisor restarts **only that process** (today one exit stops the whole
      container). *Turns a hard Render kill into a 2–5 s self-restart of one process.*

### Phase 2 — Structural memory savings (1–2 sessions) · choose one option
- [x] **2.A Run the alert worker inside the web process** (done, approved — DECISIONS #77) (one background task, guarded by a database lease so it
      can never run twice). Saves the worker's whole interpreter and imports: **≈ −110 to −130 MB**. Trade-off:
      a slow worker cycle shares CPU with page requests (mitigated by running it at low priority in its own thread
      and pausing while requests are in flight). **Needs your approval:** CLAUDE.md §4 asks for a separate worker
      process; the reason for that rule (no duplicate schedulers) is still met by the lease.
- [ ] **2.B Keep two processes but slim both**: replace yfinance + pandas with a small dedicated client for the few
      endpoints used (chart/history, quote, search, statements), parsing JSON directly into the app's own types.
      Saves **≈ −60 to −90 MB per process**; also faster imports and cold starts. Larger change: every provider
      path needs regression tests against recorded responses; same endpoints and limits as today (no change in how
      the provider is accessed).
- [ ] **2.C Lazy heavy imports**: load exchange_calendars and other heavy modules only on first use, and only the
      calendars for NSE/BSE/NYSE/Nasdaq. *≈ −20 to −40 MB in whichever process does not need them.*

Recommendation: **2.A first** (largest saving, smallest change), then 2.C. Keep 2.B for later if headroom is still
thin.

### Phase 3 — Faster pages: server side (1–2 sessions)
- [x] **3.1 Pre-warm what you look at** (6 symbols per cycle, round-robin; plus the Macro watchboard and official statistics): during quiet periods the worker refreshes, for watchlist and holdings
      symbols only, the description, fundamentals, news, peers, earnings and daily history into the persisted cache.
      Opening those pages then reads the database (tens of milliseconds) instead of calling providers (1–3 s).
- [x] **3.2 News tab** (sources in parallel with per-source time limits; merged-list cache not yet): fetch the three headline sources in parallel with a short per-source timeout (1.5 s),
      show what has arrived, and cache the merged list for 10 minutes.
- [x] **3.3 Macro page** (warmed by the worker instead of a separate snapshot): serve the watchboard from one persisted, worker-refreshed snapshot instead of fetching
      every series on page load (18 s → under 1 s).
- [ ] **3.4 Cache assembled views**: persist the computed Description/Peers/Earnings payloads for a short time
      (5–15 min), so switching tabs or revisiting is instant.
- [x] **3.5 Keep small calls fast** (market sessions answered on the event loop from a 30 s memo; AI status cached 5 min in the browser): answer `/api/ai/status`, `/api/market/sessions` and other tiny shared calls
      from memory without touching the thread pool, so they never queue behind slow work.

### Phase 4 — Faster pages: browser side (1 session)
- [x] **4.1 Long-lived caching for hashed assets**: `Cache-Control: public, max-age=31536000, immutable` on
      `/assets/*` (file names change on every build). *Repeat visits stop re-checking ~1.3 MB of JavaScript.*
- [x] **4.2 Prefetch on intent** (instrument links and table rows: page code + quote + description after a 120 ms rest): when the pointer rests on, or a phone scrolls past, an instrument link, prefetch
      its page code and first data (description + quote). Clicks then open instantly.
- [~] **4.3 Fetch once, reuse everywhere** (AI status; more to tune): longer client cache times for data that changes slowly (fundamentals,
      sessions, AI status, mappings), and share one request across tabs of the same company.
- [ ] **4.4 Instant revisits**: let the service worker (already present for the offline view) serve the last
      response for read-only API calls immediately and refresh in the background, clearly marked as refreshing.
- [ ] **4.5 Trim the main bundle** (397 KB → under 250 KB): move rarely used parts (AI dialog, import mapping form,
      research export, lab) and heavy libraries behind on-demand loading.
- [x] **4.6 Lighter effects where they cost most** (phones and touch devices default to calm effects; animation pauses in hidden tabs): automatically use the calm effects mode on phones, on
      battery-saver, and when the browser reports reduced motion; keep the full look on desktop. Pause background
      animation when the tab is hidden.

### Phase 5 — Cold starts on Render Free (decision for you)
Render Free stops the service after 15 idle minutes; the next visit waits for a restart (30–60 s), and alerts are not
evaluated while it sleeps. Options:
- [ ] **5.A Keep it awake** with a free uptime monitor that requests `/api/health` every 10–14 minutes. One service
      running all month uses about 730 of the 750 free instance hours. Trade-offs: memory is then always in use
      (Phases 1–2 matter more), and check Render's current Free-tier terms before relying on this.
- [ ] **5.B Faster wake-up**: smaller imports (2.B/2.C) and a lighter first page shorten the restart.
- [ ] **5.C Paid instance**: Render Starter removes sleeping but still has 512 MB, so Phases 1–2 are needed either
      way; a 2 GB plan removes the memory concern but costs more.

## 4. Results so far (12 Nov 2026, phases 0–1)
Same soak test (18 companies × 17 endpoints, live data, production entrypoint), local:

| | Before | After phase 1 |
| --- | --- | --- |
| Web process after 18 companies | 342 MB and still rising (~7–8 MB per company) | **243 MB, flat** (+7 MB over the last 12 companies) |
| Worker | 131 MB | 132 MB (reports its memory each cycle; restarts itself above 180 MB) |
| Supervisor + web + worker | ~500 MB | **399 MB** (phase 1) → **270 MB** with 2.A (worker inside web) |

Production (Render, 12 Nov 2026, after 2.A): the same browse of 8 companies × 6 tabs that previously caused two
outages ran without any — total memory 287–321 MB (web peak 308 MB) with alerts evaluating inside the web
process; Settings → Data status shows "276 MB of 512 MB · alerts run inside the web process".

Next: 2.C (lazy heavy imports), 1.7 (streaming large SEC documents), and phases 3–4 speed work.

### Speed results (local, live data, 12 Nov 2026)
| Call | Watchlist/holdings symbol (pre-warmed) | Other symbol |
| --- | --- | --- |
| Description tab | 0.13 s (US), 0.01 s (India) | 3.3 s, 2.7 s |
| Price history (6M) | 0.01 s | 0.55–0.6 s |
| News tab | 0.7–0.9 s | 1.2–1.9 s |
| Macro: watchboard / official statistics | 0.07 s / 0.01 s | was 9.7 s / 17.6 s cold |
| Market sessions | 0.03 s | (was up to 1.1 s when queued) |

## 5. How we will know it worked
- Soak test (0.3): total ≤ 400 MB after 24 companies × all tabs; web memory flat after the first 6 companies.
- Production (0.1): a week with no memory restarts; peak total shown in Settings ≤ 420 MB.
- Speed: watchlist companies' Description/News/Peers under 300 ms from cache; Macro under 1 s; repeat visits load
  JavaScript from the browser cache.
