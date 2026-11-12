# Indian company data — licensed source options (research, 12 Nov 2026)

Purpose: choose a permitted source for what MarketDesk cannot show today for NSE/BSE listings — 10+ years of
official financials, the quarterly shareholding pattern (promoter / FII / DII / public, pledges) and filing documents
(annual reports, results, announcements). See `docs/INDIA_FINANCIALS_PLAN.md` phases 4–6. Nothing has been bought.

**Why a licence is needed.** NSE's website terms prohibit "any systematic or automated data collection activities
(including scraping, data mining, data extraction and data harvesting)" ([NSE terms of use][nse-terms]); the NSE Data
portal requires express written consent ([NSE Data terms][nse-data-terms]). Research sites (screener.in, Trendlyne,
Value Research) build their tables from exchange filings under their own licences; their pages are not a source.

**Prices below are as published or reported in November 2026, several unverified — confirm before buying.**

| Option | What it covers | Delivery | Cost (indicative) | Fit for MarketDesk |
|---|---|---|---|---|
| **NSE Data & Analytics — Corporate Data** (NSE's licensed data arm) | Company financial results incl. segment-wise results, corporate data; historical files | End-of-day files / feed ([corporate data spec][nse-spec], [data vending][nse-vend]) | Not published. One developer write-up reports ₹5 lakh/year (EOD file), ₹10.6 lakh (leased line) — **unverified** ([DEV post][dev]) | Official and complete, but priced for businesses; licence terms for a personal tool need asking. |
| **BSE corporate data** (BSE Market Data Products) | Announcements, financial results, shareholding patterns, corporate actions, board meetings; **history since 2006** | EOD subscription; XML and XBRL ([BSE products][bse-products], [Deutsche Börse page][dbag]) | Rate card on BSE's pricing sheet ([BSE pricing sheet][bse-price]); a forum post cites ~₹9 lakh + GST/year for real-time announcements — **anecdotal**. Domestic enquiries: datafeed@bseindia.com | Official, XBRL fits our statement shape (like SEC). Business pricing. |
| **TrueData — Corporate & Fundamental Data API** (authorised NSE/BSE/MCX vendor) | Results, balance sheets, ratios, **shareholding patterns (promoter/FII/DII/public)**, corporate-actions calendar | REST API ([TrueData APIs][truedata-api]) | Not published; depends on exchange, symbols and data type, exchange fees separate ([TrueData pricing][truedata-price]). Evaluation account possible. | Best functional fit (shareholding included) from an authorised vendor; price on request. |
| **Accord Fintech — ACE Datafeed** (data behind ACE Equity) | Latest and historical data of all listed companies, standardized statement formats | FTP and API ([Accord via BSE vendor list][bse-products]) | Not published; contact info@accordfintech.com | Institutional-grade depth; likely institutional pricing. |
| **EODHD — Fundamentals API** (global vendor) | Income statement, balance sheet, cash flow for NSE tickers (some tickers stale) | REST API, JSON ([example: TCS.NSE][eodhd]) | Plans with fundamentals reported from ~$59.99/month; All-in-one $99.99/month; monthly, no long-term commitment — **check current page** | Cheapest to try; coverage and freshness uneven; shareholding pattern not confirmed; confirm its right to redistribute Indian exchange data for display. |
| **Financial Modeling Prep** (global vendor) | Standardized statements; lists NSE among exchanges; India coverage depth unconfirmed ([FMP docs][fmp]) | REST API | ~$99/month and up (third-party listing) | Similar to EODHD; verify NSE coverage on our symbols first. |

## Recommendation

1. **Trial before buying, on the owner's own symbols.** Ask TrueData for an evaluation account (covers shareholding,
   authorised vendor) and, in parallel, take one month of EODHD fundamentals (cheapest; cancel anytime). Check each on
   the watchlist and holdings: years of history, quarterly coverage, restatements, shareholding fields, freshness
   after results, and **whether the licence allows display in a private two-user tool**.
2. If both are adequate, prefer the **authorised Indian vendor** (TrueData) for licence clarity; if neither is, ask
   BSE (datafeed@bseindia.com) for a quote on EOD corporate data in XBRL — the closest match to how SEC data works here.
3. Integration (one PR, after the owner chooses): a new provider behind the existing statements shape
   (`services/reported.py`, `financials.normalize_statements`), key as a backend secret, cached and labelled with the
   source and filing dates; shareholding on the Holders tab; documents as links on the Filings tab. Until then the
   current provider statements stay, labelled unofficial.

## What I need from the owner
- Which option(s) to trial, and the trial or subscription credentials (entered as server secrets, never in chat).

[nse-terms]: https://www.nseindia.com/nse-terms-of-use
[nse-data-terms]: https://dotexdata.nseindia.com/TermsAndConditions/TermsofUse.pdf
[nse-spec]: https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Download_Technical_Specification_Corporate_Data.pdf
[nse-vend]: https://nseindia.com/nse-data-and-analytics/data-information-vending
[dev]: https://dev.to/datadaemon/is-there-an-nse-india-api-for-corporate-announcements-corporate-actions-and-bulk-deals-json-2d48
[bse-products]: https://www.bseindia.com/market_data_products.html
[bse-price]: https://mock.bseindia.com/downloads1/Information_Products_Pricing_Sheet.pdf
[dbag]: https://mds.deutsche-boerse.com/mds-en/real-time-data/data-cooperations/corporate-data
[truedata-api]: https://www.truedata.in/market-data-apis
[truedata-price]: https://www.truedata.in/information/pricing
[eodhd]: https://eodhd.com/financial-summary/TCS.NSE
[fmp]: https://site.financialmodelingprep.com/how-to/financial-statements-apis-at-scale-how-to-access-balance-sheets-income-statements-and-cash-flow-data-across-thousands-of-companies
