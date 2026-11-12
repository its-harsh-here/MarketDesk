"""Reported financial statements for listings outside SEC coverage (India first), from the market-data provider's
statement tables, normalized into the same line shape as the SEC statements (``services.financials``) so the same
tables, ratios and analysis run on them. See docs/INDIA_FINANCIALS_PLAN.md.

These are unofficial provider figures, labelled as such. Nothing is derived to fill a gap except the few lines with
an explicit formula below (each says so); a period the provider did not report stays missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

PROVIDER_FORM = "Provider statements"


@dataclass(frozen=True)
class PLine:
    key: str
    label: str
    statement: str  # income | balance | cashflow
    kind: str  # duration | instant
    unit: str  # currency | per_share | shares
    tags: tuple[str, ...]  # provider row names, first available wins (period by period)
    absolute: bool = False  # cash outflows reported negative (capex, dividends): shown as positive amounts


# Screener-style coverage: the SEC line keys (so the analysis reuses them) plus the lines Indian results commonly
# carry (other income, interest, EBITDA, working-capital items, dividends paid).
LINES: tuple[PLine, ...] = (
    PLine("revenue", "Revenue", "income", "duration", "currency", ("TotalRevenue", "OperatingRevenue")),
    PLine("cost_of_revenue", "Cost of revenue", "income", "duration", "currency", ("CostOfRevenue", "ReconciledCostOfRevenue")),
    PLine("gross_profit", "Gross profit", "income", "duration", "currency", ("GrossProfit",)),
    PLine("operating_expense", "Operating expenses", "income", "duration", "currency", ("OperatingExpense",)),
    PLine("ebitda", "EBITDA", "income", "duration", "currency", ("EBITDA", "NormalizedEBITDA")),
    PLine("operating_income", "Operating income", "income", "duration", "currency", ("OperatingIncome", "EBIT")),
    PLine("other_income", "Other income (non-operating)", "income", "duration", "currency", ("OtherNonOperatingIncomeExpenses", "OtherIncomeExpense")),
    PLine("interest_expense", "Interest expense", "income", "duration", "currency", ("InterestExpense", "InterestExpenseNonOperating")),
    PLine("pretax_income", "Income before tax", "income", "duration", "currency", ("PretaxIncome",)),
    PLine("income_tax", "Income tax expense", "income", "duration", "currency", ("TaxProvision",)),
    PLine("net_income", "Net income", "income", "duration", "currency", ("NetIncomeCommonStockholders", "NetIncome")),
    PLine("eps_diluted", "Diluted EPS", "income", "duration", "per_share", ("DilutedEPS", "BasicEPS")),
    PLine("shares_diluted", "Diluted weighted-average shares", "income", "duration", "shares", ("DilutedAverageShares", "BasicAverageShares")),
    PLine("cash", "Cash and equivalents", "balance", "instant", "currency", ("CashCashEquivalentsAndShortTermInvestments", "CashAndCashEquivalents")),
    PLine("receivables", "Receivables", "balance", "instant", "currency", ("Receivables", "AccountsReceivable")),
    PLine("inventory", "Inventory", "balance", "instant", "currency", ("Inventory",)),
    PLine("current_assets", "Current assets", "balance", "instant", "currency", ("CurrentAssets",)),
    PLine("net_ppe", "Net property, plant and equipment", "balance", "instant", "currency", ("NetPPE",)),
    PLine("total_assets", "Total assets", "balance", "instant", "currency", ("TotalAssets",)),
    PLine("payables", "Payables", "balance", "instant", "currency", ("AccountsPayable", "Payables")),
    PLine("current_liabilities", "Current liabilities", "balance", "instant", "currency", ("CurrentLiabilities",)),
    PLine("total_liabilities", "Total liabilities", "balance", "instant", "currency", ("TotalLiabilitiesNetMinorityInterest",)),
    PLine("equity", "Shareholders' equity", "balance", "instant", "currency", ("StockholdersEquity", "CommonStockEquity")),
    PLine("long_term_debt", "Long-term debt", "balance", "instant", "currency", ("LongTermDebt", "LongTermDebtAndCapitalLeaseObligation")),
    PLine("current_debt", "Current debt", "balance", "instant", "currency", ("CurrentDebt", "CurrentDebtAndCapitalLeaseObligation")),
    PLine("total_debt", "Total debt", "balance", "instant", "currency", ("TotalDebt",)),
    PLine("operating_cash_flow", "Operating cash flow", "cashflow", "duration", "currency", ("OperatingCashFlow", "CashFlowFromContinuingOperatingActivities")),
    PLine("investing_cash_flow", "Investing cash flow", "cashflow", "duration", "currency", ("InvestingCashFlow",)),
    PLine("financing_cash_flow", "Financing cash flow", "cashflow", "duration", "currency", ("FinancingCashFlow",)),
    PLine("depreciation", "Depreciation and amortization", "cashflow", "duration", "currency", ("DepreciationAndAmortization", "Depreciation", "ReconciledDepreciation")),
    PLine("capex", "Capital expenditure", "cashflow", "duration", "currency", ("CapitalExpenditure", "PurchaseOfPPE"), absolute=True),
    PLine("free_cash_flow", "Free cash flow", "cashflow", "duration", "currency", ("FreeCashFlow",)),
    PLine("dividends_paid", "Dividends paid", "cashflow", "duration", "currency", ("CashDividendsPaid", "CommonStockDividendPaid"), absolute=True),
)  # fmt: skip

# Days after a fiscal year end by which the annual results are taken to be public, for valuation bands (which use,
# each day, only figures already published). Indian listed companies must publish audited annual results within
# 60 days of the year end (SEBI LODR Regulation 33); elsewhere a conservative 90 days.
PUBLISH_LAG_DAYS = {"IN": 60}
DEFAULT_PUBLISH_LAG_DAYS = 90


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _day(col: Any) -> date | None:
    if isinstance(col, date):
        return col if type(col) is date else col.date()  # pandas Timestamp / datetime
    try:
        return date.fromisoformat(str(col)[:10])
    except ValueError:
        return None


def frame_rows(df: Any) -> dict[str, dict[date, Decimal]]:
    """{row name: {period end: value}} from a provider statement frame (rows = items, columns = period ends)."""
    out: dict[str, dict[date, Decimal]] = {}
    if df is None or getattr(df, "empty", True):
        return out
    cols = [(c, _day(c)) for c in df.columns]
    for name in df.index:
        row = df.loc[name]
        vals = {}
        for col, d in cols:
            if d is None:
                continue
            v = _dec(row[col])
            if v is not None:
                vals[d] = v
        if vals:
            out[str(name)] = vals
    return out


def normalize(
    rows: dict[str, dict[date, Decimal]],
    period: str,
    currency: str | None,
    source: str,
    max_periods: int,
    publish_lag_days: int | None = None,
) -> dict:
    """The normalized statement dict (``financials.normalize_statements`` shape) from provider rows."""
    unit_ccy = currency or "statement currency"
    lines: list[dict] = []
    ends: set[date] = set()
    for pl in LINES:
        merged: dict[date, tuple[Decimal, str]] = {}
        for tag in pl.tags:  # earlier tags take priority, period by period
            for end, v in rows.get(tag, {}).items():
                merged.setdefault(end, (abs(v) if pl.absolute else v, tag))
        unit = {"currency": unit_ccy, "per_share": f"{unit_ccy}/shares", "shares": "shares"}[pl.unit]
        values = []
        for end in sorted(merged, reverse=True)[:max_periods]:
            v, tag = merged[end]
            filed = (end + timedelta(days=publish_lag_days)).isoformat() if publish_lag_days is not None else None
            values.append({"value": v, "unit": unit, "end": end, "start": None, "form": PROVIDER_FORM,
                           "filed": filed, "accession": None, "prior": [], "restated": False, "tag": tag,
                           "taxonomy": None, "source_url": None})  # fmt: skip
            ends.add(end)
        entry = {"key": pl.key, "label": pl.label, "statement": pl.statement, "kind": pl.kind, "values": values,
                 "status": "available" if values else "unavailable"}  # fmt: skip
        if not values:
            entry["reason"] = f"The provider reports no {period} {pl.label.lower()} for this company."
        lines.append(entry)
    # A period the source covers only with a stray line or two (e.g. one capex figure for an older year) would be an
    # almost empty column: keep periods with at least a third of the best-covered period's lines.
    count = {e: sum(1 for line in lines for v in line["values"] if v["end"] == e) for e in ends}
    best = max(count.values(), default=0)
    ends = {e for e in ends if count[e] * 3 >= best}
    for line in lines:
        line["values"] = [v for v in line["values"] if v["end"] in ends]
        if not line["values"] and line["status"] == "available":
            line["status"] = "unavailable"
            line["reason"] = f"The provider reports no {period} {line['label'].lower()} for this company."
    return {
        "period": period,
        "taxonomy": None,
        "template": "industrial",
        "origin": "provider",
        "source": source,
        "period_ends": sorted(ends, reverse=True)[:max_periods],
        "currency": currency,
        "lines": lines,
    }


def publish_lag(country: str | None) -> int:
    return PUBLISH_LAG_DAYS.get(country or "", DEFAULT_PUBLISH_LAG_DAYS)


def statement_currency(symbol: str, country: str | None) -> str | None:
    """Indian listings (NSE/BSE) report in rupees under Ind AS; elsewhere the provider's tables do not say."""
    if symbol.upper().endswith((".NS", ".BO")) or country == "IN":
        return "INR"
    return None


# ------------------------------------------------------------------------------------------- cache codec
def to_json(st: dict) -> dict:
    def conv(x):
        if isinstance(x, Decimal):
            return format(x, "f")
        if isinstance(x, date):
            return x.isoformat()
        if isinstance(x, dict):
            return {k: conv(v) for k, v in x.items()}
        if isinstance(x, list):
            return [conv(v) for v in x]
        return x

    return conv(st)


def from_json(d: dict) -> dict:
    st = dict(d)
    st["period_ends"] = [date.fromisoformat(e) for e in d["period_ends"]]
    st["lines"] = [
        {
            **line,
            "values": [
                {**v, "value": Decimal(v["value"]), "end": date.fromisoformat(v["end"])} for v in line["values"]
            ],
        }  # fmt: skip
        for line in d["lines"]
    ]
    return st
