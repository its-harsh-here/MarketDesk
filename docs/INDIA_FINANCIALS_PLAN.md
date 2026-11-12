# Indian company financials — plan

Goal: for NSE/BSE listings, research depth comparable to what Indian research sites (for example screener.in)
offer, while keeping MarketDesk's rules: real data only, sources stated, nothing derived without a stated formula,
missing never shown as zero, and no scraping of sites whose terms forbid it.

## Sources (what may be used)

| Source | What it has | Status |
|---|---|---|
| Market-data provider statement tables (current feed) | Income statement, balance sheet, cash flow: ~4 fiscal years, ~5 quarters; Indian balance sheet and cash flow are half-yearly | **Used now** (phase 1). Unofficial; labelled as such. |
| Exchange filings (NSE/BSE XBRL financial results, shareholding pattern, announcements) | Official quarterly and annual results, 10+ years; promoter/FII/DII holdings, pledges; annual reports, concall and rating announcements | **Needs a decision.** The exchange websites' terms restrict automated access; a licensed exchange data product or a vendor that redistributes it is the permitted route. Verify terms and cost before building. |
| Research sites (screener.in and similar) | Curated tables built from exchange filings | **Not used.** Their terms do not permit scraping; used only as a reference for which views are useful. |
| Company investor-relations pages | PDFs of results and annual reports | Links only, never parsed into figures without an owner decision. |

## Phases

1. **Full provider statements (done, 12 Nov 2026).** Indian listings get the same Financial statements panel as US
   filers: 30+ lines across the three statements (revenue, EBITDA, other income, interest, tax, EPS, receivables,
   inventory, payables, current assets/liabilities, total debt, investing/financing cash flow, dividends paid),
   annual and quarterly, in ₹ crore. Fiscal-year and quarter-month column names (FY2026, Sep 2026). Periods the
   source covers with only a stray line are dropped; a skipped quarter is named, never derived. Financial analysis
   (margins, growth, CAGR, returns, per share, common size) runs on these figures, and valuation bands work with
   each fiscal year taken as public 60 days after its end (the SEBI LODR deadline for annual audited results).
2. **Indian ratios (done, 12 Nov 2026).** ROCE, interest coverage, current ratio, debt to equity, dividend payout,
   debtor / inventory / payable days and the cash conversion cycle, each with its formula.
3. **Screener metrics (next).** Add ROCE, operating margin, 3-year sales and profit CAGR, debt to equity and
   interest coverage to the screener catalog, from the stored snapshot, so filters like "ROCE ≥ 15% and debt to
   equity ≤ 0.5" run across a list. Needs the snapshot to store these inputs (snapshot version bump).
4. **Ten-year history and official figures (needs owner decision).** Only via an exchange-licensed source; once
   chosen, add it as a provider behind the same normalized-statement shape with filing dates and links, so SEC and
   Indian filings render identically (including restatement markers).
5. **Shareholding pattern (needs the same source).** Promoter, FII, DII and public holdings by quarter, promoter
   pledges, and changes quarter on quarter, on the Holders tab.
6. **Documents (needs the same source).** Annual reports, results PDFs, concall transcripts and credit-rating
   announcements as dated links on the Filings tab; no article bodies stored.
7. **Peer table, Indian style.** Industry peers with market cap, P/E, ROCE, sales growth and OPM side by side
   (the Peers tab already compares; extend its columns once phase 3 stores the inputs).

## Rules that stay

- Provider figures are labelled unofficial; filing-backed figures link to the filing.
- No fourth quarter or missing period is derived from annual minus quarters.
- Ratios use ending balances and say so; quarterly figures are not annualized.
- Indian amounts display in ₹ crore; exact period ends are in each column header's tooltip.
