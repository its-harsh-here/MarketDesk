# Upgrade plan (phased)

Owner request (3 Nov 2026): work through the roadmap prompt pack (M00–M14 plus the final release check) in phases.
Rules: `docs/UPGRADE_RULES.md`. One phase at a time: each phase is implemented, verified, committed to `main` with the
owner's co-author trailer, and recorded in `docs/UPGRADE_STATUS.md` before the next starts. A phase may need more
than one session. Credential-gated integrations are built and tested with fixtures and stay disabled until the owner
supplies credentials; live verification is reported separately.

Legend: ✅ done · 🟡 partly exists (see `docs/UPGRADE_STATUS.md` capability map) · ⬜ not started · 🔑 needs owner credentials.

| Phase | Milestone | Starting point | Remaining work (summary) | Owner inputs |
| --- | --- | --- | --- | --- |
| 1 | **M00** Operational foundation | 🟡 login, health/readiness, storage check, Postgres | Login trace + production-like reproduction; request IDs; distinct 401/429/5xx/network UI; HTTPS/proxy cookie checks; status additions (version, migration, provider endpoints); DB-agnostic backup/restore; worker-only settings; Render docs; login screenshots | none |
| 2 | **M01** India + US | 🟡 any Yahoo symbol works in native currency | Canonical instrument identity (country, exchange, MIC, provider symbol, type, tz) + migration of existing rows; region/currency filters; disambiguated search; verified exchange calendars (NSE/BSE, NYSE/Nasdaq) with holiday/closed/unknown; normalized comparison chart (≤3); tests incl. DST | none |
| 3 | **M02** Company workspace | 🟡 fundamentals panel, corporate actions | Tabs (Overview/Financials/Filings/Events); SEC submissions + companyfacts adapter (ticker→CIK, fair access, cache); normalized source-linked facts; annual/quarterly tables; ratios with formulas; scheduled refresh | 🔑 `SEC_USER_AGENT` with a real contact (no key) |
| 4 | **M05** Alerts, briefings, inbox | 🟡 price alerts, rule briefing, in-app list | Rule types (crossing, volume/volatility vs comparable sessions, filings/events), quiet hours, cooldown; unified inbox; delivery dedup; morning/end-of-session briefing on exchange calendars | optional email/Telegram settings |
| 5 | **M08** USD portfolios + FX | 🟡 INR ledger | Currency accounts; explicit FX conversion events; base-currency overview with completeness; CSV account/currency; migration from populated copy with exact INR comparison | none |
| 6 | **M10** Decision journal | 🟡 journal | Structured thesis, immutable versions + evidence snapshots, review queue/history, version diff | none (Grok challenge after M03) |
| 7 | **M06** Screener + peers | ⬜ | Declared universe, normalized nullable dataset, filters, saved screens, peers (≤5), sector heatmap | none |
| 8 | **M09** Performance + risk | ⬜ | Cash-flow-aware returns (documented), benchmark, exposures, drawdown/volatility, aligned correlations, rebalance simulation | needs M08 + history |
| 9 | **M11** Valuation lab | ⬜ | DCF (non-financials), multiples, sensitivity, stress; deterministic, hand-checked tests | none |
| 10 | **M03** Grok research assistant | ⬜ | xAI client (verified docs), evidence packages, typed read-only tools, structured cited output, streaming drawer, budgets/rate limits, saved answers | 🔑 `XAI_API_KEY`, `XAI_MODEL` |
| 11 | **M07** Earnings + filing changes | ⬜ | Earnings calendar, reported-period changes, filing diff with excerpts, guidance/risk timelines, bull/base/bear brief | needs M02 (+ M03) |
| 12 | **M04** Streaming dashboard | 🟡 polling dashboard | Alpaca adapter (entitled feed), central upstream + SSE/WebSocket fan-out, gap backfill, feed labels, workstation layout | 🔑 Alpaca key/secret + feed choice |
| 13 | **M12** Macro + sector | ⬜ | Verified sources, normalized series with vintages, watchboard, sector-relative view | 🔑 depends on chosen sources |
| 14 | **M13** Paper investing + research tests | ⬜ | Isolated paper ledger, daily-bar engine with conservative fills, reproducible runs | needs a verified historical dataset |
| 15 | **M14** Workspaces + offline | 🟡 command palette, density | Presets, PWA read-only offline snapshot, exports, usage panel | none |
| 16 | Final release check | — | Audit all completed milestones, run every check, update docs | — |

Order rationale: the roadmap's sequence (M00 → M01 → M02 → M03 → M04 → M05), adjusted so that credential-free,
correctness-critical work (M05, M08, M10) proceeds while Grok/Alpaca credentials are unavailable. M03 and M04 move
earlier as soon as their credentials exist.

## Progress
- Phase 1 (M00): implemented and verified locally; live verification after deploy recorded in `docs/UPGRADE_STATUS.md`.
- Phase 2 (M01): next.
