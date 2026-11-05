# Terminal roadmap — everything about one security, in one place

Owner request (4 Nov 2026): after the current roadmap (`docs/UPGRADE_PLAN.md`, M00–M14 and the final check), evolve
MarketDesk toward a professional-terminal experience: every piece of information about a particular stock, reachable
by keyboard, with each figure traceable to its source. This document maps what such terminals offer per security to
what MarketDesk has, which **free or owner-licensed** sources could fill each gap for **India (NSE/BSE)** and the
**US**, and a phased plan (T1–T10) to follow the current roadmap.

It is a plan, not a commitment that every function is achievable: several terminal functions depend on licensed data
(consensus estimates, real-time consolidated quotes, Indian exchange data feeds). Those phases are gated on an owner
decision and say so.

## Principles (unchanged from `CLAUDE.md` and `docs/UPGRADE_RULES.md`)
- Every value shows its source, period or observation date, and retrieval time; missing data is an explained em
  dash, never zero, never invented. Model output (Groq/xAI) only summarizes retrieved documents, with citations.
- Only sources whose current API and terms are verified, used within their rate limits. No scraping that a site's
  terms forbid, no evasion of limits, no purchases without the owner's authorization.
- Personal research only: no order execution, recommendations or redistribution of licensed data.
- A per-security **coverage panel** says which domains are available for this listing and why others are not (e.g.
  "Insider transactions: US issuers only (SEC Form 4)").

## What a terminal shows per security, and where MarketDesk stands

Function names are the common terminal shorthand used in university guides (e.g.
[Lerner/UDel function list](https://lerner.udel.edu/seeing-opportunity/bloomberg-functions-list),
[CFI](https://corporatefinanceinstitute.com/resources/equities/bloomberg-functions-shortcuts-list/)). MarketDesk
copies none of that branding; the codes are only a checklist.

Legend: ✅ have · 🟡 partial · ⬜ missing · 🔒 needs licensed data or an owner decision.

| Area (terminal shorthand) | What it covers | MarketDesk today | US source (free unless noted) | India source |
| --- | --- | --- | --- | --- |
| Description (DES) | Identity, business, key stats, listings, next events | 🟡 header, fundamentals panel, identity | SEC submissions (SIC, addresses, fiscal year end); 10-K Item 1 text | Yahoo profile (unofficial); annual report is a PDF → 🔒/manual |
| Price graph & history (GP/HP) | Charts, intraday, comparisons, events on chart | ✅ daily chart, compare ≤3; ⬜ intraday, event markers | Yahoo (unofficial); Alpaca (owner key, M04) | Yahoo (delayed, unofficial) |
| Financial analysis (FA) | Statements, ratios, segments, per-share, history | 🟡 SEC annual/quarterly (US), ratios; Yahoo 4 FY (screener) | SEC companyfacts/frames; segments need filing XBRL instances | Yahoo statements (unofficial); exchange XBRL results 🔒 |
| Earnings (EE, ERN) | Dates, history, surprises, guidance | 🟡 results release via 8-K (AI) | 8-K Item 2.02 history (dates, releases); estimates 🔒 | Board-meeting/results announcements 🔒 |
| Analyst views (ANR) | Consensus, targets, ratings | ⬜ | 🔒 paid provider; Yahoo analyst data is unofficial | 🔒 |
| Dividends & actions (DVD) | Dividend/split history, ex-dates, buybacks | 🟡 Yahoo actions, Events tab | Yahoo; 8-K/10-Q text for buybacks | Yahoo; exchange corporate actions 🔒 |
| Holders (HDS) | Institutions, insiders, promoters | ⬜ | SEC DERA Form 13F and Insider Transactions data sets (quarterly); Form 4 XML per filing | Quarterly shareholding pattern (promoter/FII/DII/public, pledges) — exchange filings 🔒 |
| News & filings (CN) | Tagged news, filings, press releases | 🟡 SEC filings list, results release | SEC submissions + 8-K items; company press releases (Ex-99) | Exchange announcements 🔒; company IR pages |
| Relative value (RV) | Peers on multiples and growth | ✅ M06 peers; ⬜ history of multiples | Derived from prices + statements | Same |
| Risk (BETA, correlation) | Beta, volatility, drawdown | 🟡 volatility (M06); M09 adds portfolio risk | Derived from prices | Derived from prices |
| Short interest | Shares short, days to cover | ⬜ | FINRA Equity Short Interest (API with developer credentials; files) | Not published comparably → n/a |
| Options (OMON) | Chains, IV, OI, put/call | ⬜ | 🔒 entitlement (Alpaca options data plan to verify); Yahoo unofficial | NSE option chain web page — terms unverified 🔒 |
| Supply chain (SPLC) | Customers, suppliers, competitors | ⬜ | 10-K major-customer disclosures (model extraction with citations) | Annual report 🔒 |
| Economic context (ECO, WEI) | Calendar, macro series, indices | ⬜ (M12 planned) | FRED (free key, attribution) | RBI/MOSPI releases — to verify in M12 |
| Screener (EQS) | Screen a universe | ✅ M06 (declared universes) | — | — |
| Monitor (MOST, launchpad) | Movers, linked panels, layouts | 🟡 overview, watchlists; M14 workspaces | — | — |

### Source notes (checked 4 Nov 2026)
- **SEC EDGAR APIs** — `data.sec.gov` submissions, companyconcept, companyfacts and frames; no API key; nightly bulk
  ZIPs; automated access must follow SEC.gov's access policy (MarketDesk already sends `SEC_USER_AGENT` and paces
  requests) — [SEC: EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).
- **SEC DERA data sets** — Insider Transactions (Forms 3/4/5, quarterly, from 2006) and Form 13F holdings, listed in
  the [DERA Data Library](https://www.sec.gov/dera/data) ([insider data sets](https://www.sec.gov/dera/data/form-345)).
  Quarterly cadence: "latest" insider trades need per-filing Form 4 XML from submissions.
- **FINRA short interest** — public files and an API; the API likely needs free developer credentials (to confirm) —
  [FINRA Equity Short Interest](https://www.finra.org/finra-data/browse-catalog/equity-short-interest/data).
- **FRED** — free API key; attribution required; some series carry third-party copyright (check before showing) —
  [FRED API](https://fred.stlouisfed.org/docs/api/fred/v2/).
- **BSE** — announcements, results and shareholding data are sold as licensed "Corporate Data" products
  ([BSE market data products](https://www.bseindia.com/market_data_products.html)); results are filed in XBRL.
- **NSE** — publishes shareholding, announcements and deal data on its website; its terms of use could not be read
  from this environment (the page refused automated access), so automated use is **unverified** and stays gated.
- **Yahoo via yfinance** — unofficial; already the price source (see README "Real data only"). Analyst and options
  data from it would be labelled unofficial and off by default.

## Phases (after the current roadmap's final check)

Each phase follows the upgrade rules: one at a time, fixtures first, migration rehearsal on a production copy, live
verification reported separately, docs updated.

### T1 — Security description page and function keys — ✅ done 5 Nov 2026 (see `docs/UPGRADE_STATUS.md`)
A single **Description** view per instrument (the landing tab): identity (all listings, ISIN/CIK where known, sector,
fiscal year end), business summary (US: 10-K Item 1 excerpt with a link; elsewhere: provider profile marked as
such), key stats grid (price, ranges, valuation, growth, leverage — from the M06 snapshot with as-of dates), next
known events, latest three filings, peers strip, ownership summary (when T3 exists), and a **coverage panel**.
**Function keys:** typing `RELIANCE.NS FA`, `AAPL HDS`, `TCS.NS RV` in the command palette jumps to that view; `?`
lists codes. Done when every tile shows source and date, and the codes are keyboard- and screen-reader-usable.

### T2 — Financial analysis depth — ✅ done 5 Nov 2026 (segments remain a stretch goal)
Ten-year annual and twelve-quarter statements where the source has them; per-share series; common-size statements;
CAGR and margin trend tables; cash-conversion and ROIC with stated formulas; restatement history (already captured
for SEC facts); historical valuation bands (P/E and EV/EBITDA ranges from daily prices and reported earnings).
US from SEC companyfacts (and frames for cross-sectional percentiles within the owner's universes). India from
Yahoo statements, labelled unofficial, until an owner-approved exchange source exists. Segment data (US) parsed from
filing XBRL instances is a stretch goal.

### T3 — Ownership and insiders
US: insider transactions from Form 4 XML (per filing, via submissions) for tracked issuers, with role, transaction
code in words, shares, price, holdings after; quarterly institutional holders from the DERA 13F data sets processed
offline into a compact per-CUSIP table for tracked instruments only. India: quarterly shareholding pattern
(promoter, FII, DII, public, pledged) **only after the owner chooses a permitted source** (BSE licence, or verified
NSE terms). Alerts on new insider filings reuse M05.

### T4 — Earnings and corporate events
An events calendar per security and across watchlists: past results dates (8-K Item 2.02 for US), dividends and
splits with ex-dates, buyback announcements, AGM/board meetings where a permitted source exists; earnings history
table (reported figures only). Consensus estimates and surprises are 🔒: shown only if the owner subscribes to a
provider with a licence for personal use.

### T5 — News and filings stream
A per-security stream of filings (plain-language 8-K item labels, 10-K/10-Q, proxy, 13D/G) and company press
releases, deduplicated and timestamped; optional cited AI summaries using the M03 pipeline (Groq free tier), never
uncited. Indian exchange announcements gated as in T3. No scraping of article bodies (headlines and links only, per
`CLAUDE.md`).

### T6 — Relative value and risk — ✅ done 5 Nov 2026 (short interest waits for the owner's FINRA credentials)
Peer multiples over time, z-scores within the declared universe, beta and correlation to a chosen benchmark (from
aligned daily returns), drawdown profile, liquidity (ADV, spread proxy), and US short interest with days to cover
(FINRA). Builds on M06 snapshots and M09 risk calculations.

### T7 — Options and derivatives (gated)
Read-only option chains with OI, volume, implied volatility and put/call ratios, only from a source the owner is
entitled to (verify Alpaca's options data plan; NSE F&O only with verified terms). No strategy builder or trading.

### T8 — Macro and cross-asset context
Extends M12: a per-security "context" strip (benchmark, sector index, currency, relevant rates/commodities), an
economic calendar from official release schedules, and FRED series for the US; Indian series from RBI/MOSPI once
verified. Each series shows vintage and release date.

### T9 — Workstation UX
Linked panels (one symbol drives chart, description, news and holders), saved multi-panel layouts (extends M14),
a movers monitor across the owner's universes, keyboard-only navigation across every view, and a dense "terminal"
density preset. Accessibility and the existing design tokens stay; no imitation of any vendor's look.

### T10 — Relationships (stretch)
Major customers and suppliers from US 10-K disclosures (model extraction, every item cited to the filing text),
plus the owner's own annotations. Marked low confidence by design; never presented as complete.

## Sequencing and owner inputs

| Order | Phase | Depends on | Owner input |
| --- | --- | --- | --- |
| 1 | T1 Description + function keys ✅ | M06, M14 | none |
| 2 | T2 Financial depth ✅ | M02, M11 | none (India stays unofficial until a source is chosen) |
| 3 | T6 Relative value and risk ✅ | M06, M09 | FINRA API credentials (required by FINRA's terms; free Individual account) |
| 4 | T4 Earnings and events | M07 | optional estimates provider (paid) |
| 5 | T5 News and filings | M03, M07 | none |
| 6 | T3 Ownership | M02 | India source choice (BSE licence or verified NSE terms) |
| 7 | T8 Macro context | M12 | FRED API key (free) |
| 8 | T9 Workstation UX | M04, M14 | none |
| 9 | T7 Options | M04 | options data entitlement |
| 10 | T10 Relationships | M03 | none |

## Non-goals
Order routing or execution; messaging; real-time consolidated quotes without an entitlement; bond, CDS and private
company data (no free source); redistribution of licensed data; scraping against a site's terms.
