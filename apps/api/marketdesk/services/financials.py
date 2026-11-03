"""Normalization of SEC XBRL company facts into source-linked statement lines (pure functions, no I/O).

Rules (each is tested):
- Every value keeps its taxonomy and tag, unit, period start/end, form, filing date and accession number, so it can
  be traced to the filing it came from.
- Balance-sheet lines are instants (one date); income and cash-flow lines are durations. Durations are classified by
  length: 340-380 days = annual, 80-100 days = a standalone quarter. Six- and nine-month year-to-date values are
  dropped, never mixed with standalone quarters, and a missing fourth quarter is not derived by subtraction.
- The same tag and period reported in several filings keeps the latest filing's value and lists earlier values as
  provenance; a changed value is flagged as restated.
- Lines use an explicit, ordered list of tags per template. Banks and insurers (by SIC code) use a financial-company
  template in which industrial lines such as revenue and gross profit are not mapped (shown as not applicable) rather
  than guessed. IFRS filers (ifrs-full taxonomy) have their own tag lists.
- Units must match the line: the filer's reporting currency (the currency of most of its monetary facts) for
  amounts and that currency per share for EPS. Facts in other currencies or units are not mixed in, and nothing is
  converted.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
QUARTERLY_FORMS = {"10-Q", "10-Q/A"}


@dataclass(frozen=True)
class Line:
    key: str
    label: str
    statement: str  # income | balance | cashflow
    kind: str  # duration | instant
    unit: str  # currency | per_share
    gaap: tuple[str, ...]
    ifrs: tuple[str, ...] = ()
    industrial_only: bool = False  # not mapped for banks/insurers


LINES: tuple[Line, ...] = (
    Line(
        "revenue",
        "Revenue",
        "income",
        "duration",
        "currency",
        (
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
        ),
        ("Revenue",),
        industrial_only=True,
    ),
    Line(
        "cost_of_revenue",
        "Cost of revenue",
        "income",
        "duration",
        "currency",
        ("CostOfRevenue", "CostOfGoodsAndServicesSold"),
        ("CostOfSales",),
        industrial_only=True,
    ),
    Line(
        "gross_profit",
        "Gross profit",
        "income",
        "duration",
        "currency",
        ("GrossProfit",),
        ("GrossProfit",),
        industrial_only=True,
    ),
    Line(
        "operating_income",
        "Operating income",
        "income",
        "duration",
        "currency",
        ("OperatingIncomeLoss",),
        ("ProfitLossFromOperatingActivities",),
        industrial_only=True,
    ),
    Line(
        "net_income",
        "Net income",
        "income",
        "duration",
        "currency",
        ("NetIncomeLoss",),
        ("ProfitLossAttributableToOwnersOfParent", "ProfitLoss"),
    ),
    Line(
        "eps_diluted",
        "Diluted EPS",
        "income",
        "duration",
        "per_share",
        ("EarningsPerShareDiluted",),
        ("DilutedEarningsLossPerShare",),
    ),
    Line(
        "cash",
        "Cash and equivalents",
        "balance",
        "instant",
        "currency",
        ("CashAndCashEquivalentsAtCarryingValue",),
        ("CashAndCashEquivalents",),
    ),
    Line("total_assets", "Total assets", "balance", "instant", "currency", ("Assets",), ("Assets",)),
    Line(
        "total_liabilities", "Total liabilities", "balance", "instant", "currency", ("Liabilities",), ("Liabilities",)
    ),
    Line(
        "equity",
        "Shareholders' equity",
        "balance",
        "instant",
        "currency",
        ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
        ("EquityAttributableToOwnersOfParent", "Equity"),
    ),
    Line(
        "long_term_debt",
        "Long-term debt",
        "balance",
        "instant",
        "currency",
        ("LongTermDebtNoncurrent", "LongTermDebt"),
        ("NoncurrentPortionOfNoncurrentBorrowings",),
        industrial_only=True,
    ),
    Line(
        "operating_cash_flow",
        "Operating cash flow",
        "cashflow",
        "duration",
        "currency",
        ("NetCashProvidedByUsedInOperatingActivities",),
        ("CashFlowsFromUsedInOperatingActivities",),
    ),
    Line(
        "capex",
        "Capital expenditure",
        "cashflow",
        "duration",
        "currency",
        ("PaymentsToAcquirePropertyPlantAndEquipment",),
        ("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",),
        industrial_only=True,
    ),
)
LINE_BY_KEY = {line.key: line for line in LINES}


def is_financial_company(sic: str | int | None) -> bool:
    """Banks, credit institutions, brokers and insurers (SIC 6000-6499): industrial templates do not apply."""
    try:
        code = int(sic) if sic is not None and str(sic).strip() else None
    except ValueError:
        return False
    return code is not None and 6000 <= code <= 6499


def classify_duration(start: date, end: date) -> str | None:
    days = (end - start).days + 1
    if 340 <= days <= 380:
        return "annual"
    if 80 <= days <= 100:
        return "quarterly"
    return None  # year-to-date or irregular: never mixed with standalone periods


def _currency_unit(unit: str) -> bool:
    return len(unit) == 3 and unit.isalpha() and unit.isupper()


def _per_share_unit(unit: str) -> bool:
    head, _, tail = unit.partition("/")
    return tail == "shares" and _currency_unit(head)


def _dec(v) -> Decimal | None:
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _date(v) -> date | None:
    try:
        return date.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None


@dataclass
class FactValue:
    value: Decimal
    unit: str
    taxonomy: str
    tag: str
    start: date | None
    end: date
    form: str
    filed: date
    accession: str
    restated: bool = False
    prior: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "unit": self.unit,
            "taxonomy": self.taxonomy,
            "tag": self.tag,
            "start": self.start,
            "end": self.end,
            "form": self.form,
            "filed": self.filed,
            "accession": self.accession,
            "restated": self.restated,
            "prior": self.prior,
        }


def reporting_currency(facts: dict, taxonomy: str) -> str | None:
    """The currency the filer reports most of its monetary facts in (amounts are never converted)."""
    counts: dict[str, int] = defaultdict(int)
    for concept in (facts.get(taxonomy) or {}).values():
        for unit, items in ((concept or {}).get("units") or {}).items():
            if _currency_unit(unit) and isinstance(items, list):
                counts[unit] += len(items)
    return max(counts, key=lambda u: (counts[u], u)) if counts else None


def _candidates(
    facts: dict, taxonomy: str, tag: str, line: Line, period: str, currency: str | None
) -> list[FactValue]:
    concept = (facts.get(taxonomy) or {}).get(tag) or {}
    out = []
    for unit, items in (concept.get("units") or {}).items():
        if line.unit == "currency" and unit != currency:
            continue  # other currencies (e.g. a convenience translation) are not mixed into the line
        if line.unit == "per_share" and unit != f"{currency}/shares":
            continue
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            val, end, filed = _dec(item.get("val")), _date(item.get("end")), _date(item.get("filed"))
            form, accn = str(item.get("form") or ""), str(item.get("accn") or "")
            if val is None or end is None or filed is None or not accn:
                continue  # malformed fact: skipped, never zero-filled
            start = _date(item.get("start"))
            if line.kind == "duration":
                if start is None or start > end or classify_duration(start, end) != period:
                    continue
                if form not in (ANNUAL_FORMS if period == "annual" else ANNUAL_FORMS | QUARTERLY_FORMS):
                    continue
            else:
                if start is not None:
                    continue
                if form not in (ANNUAL_FORMS if period == "annual" else QUARTERLY_FORMS | ANNUAL_FORMS):
                    continue
            out.append(FactValue(val, unit, taxonomy, tag, start, end, form, filed, accn))
    return out


def _resolve(cands: list[FactValue]) -> dict[tuple, FactValue]:
    """One value per period: the latest filing wins; earlier differing values are kept as restatement provenance."""
    by_period: dict[tuple, list[FactValue]] = defaultdict(list)
    for c in cands:
        by_period[(c.start, c.end)].append(c)
    out = {}
    for key, group in by_period.items():
        group.sort(key=lambda f: (f.filed, f.accession))
        latest = group[-1]
        earlier = [g for g in group[:-1] if g.accession != latest.accession]
        latest.prior = [{"value": g.value, "filed": g.filed, "accession": g.accession, "form": g.form} for g in earlier]
        latest.restated = any(g.value != latest.value for g in earlier)
        out[key] = latest
    return out


def normalize_statements(companyfacts: dict, sic: str | int | None, period: str, max_periods: int) -> dict:
    """Build statement lines for `period` ("annual" | "quarterly") from a companyfacts payload."""
    if period not in ("annual", "quarterly"):
        raise ValueError("period must be annual or quarterly")
    facts = companyfacts.get("facts") if isinstance(companyfacts, dict) else None
    if not isinstance(facts, dict):
        raise ValueError("companyfacts payload has no facts")
    taxonomy = "us-gaap" if "us-gaap" in facts else ("ifrs-full" if "ifrs-full" in facts else None)
    currency = reporting_currency(facts, taxonomy) if taxonomy else None
    financial = is_financial_company(sic)
    lines = []
    period_ends: set[date] = set()
    for line in LINES:
        entry = {"key": line.key, "label": line.label, "statement": line.statement, "kind": line.kind, "values": []}
        if taxonomy is None:
            entry["status"] = "unavailable"
            entry["reason"] = "No US-GAAP or IFRS facts in this filing data."
        elif financial and line.industrial_only:
            entry["status"] = "not_applicable"
            entry["reason"] = "Not mapped for banks and insurers: the industrial definition does not apply."
        else:
            tags = line.gaap if taxonomy == "us-gaap" else line.ifrs
            resolved: dict[tuple, FactValue] = {}
            for tag in tags:  # earlier tags take priority period by period
                for key, fv in _resolve(_candidates(facts, taxonomy, tag, line, period, currency)).items():
                    resolved.setdefault(key, fv)
            values = sorted(resolved.values(), key=lambda f: f.end, reverse=True)[:max_periods]
            entry["values"] = [v.to_dict() for v in values]
            entry["status"] = "available" if values else "unavailable"
            if not values:
                entry["reason"] = f"No {period} values reported under the mapped tags ({', '.join(tags)})."
            for v in values:
                period_ends.add(v.end)
        lines.append(entry)
    return {
        "period": period,
        "taxonomy": taxonomy,
        "template": "financial" if financial else "industrial",
        "period_ends": sorted(period_ends, reverse=True)[:max_periods],
        "currency": currency,
        "lines": lines,
    }


def _value_at(lines: list[dict], key: str, end: date):
    for line in lines:
        if line["key"] == key:
            for v in line["values"]:
                if v["end"] == end:
                    return v
    return None


def _ratio(name, formula, num, den, unit="ratio"):
    if num is None or den is None or den["value"] == 0 or num["unit"].split("/")[0] != den["unit"].split("/")[0]:
        return {"key": name, "formula": formula, "value": None, "unit": unit, "inputs": [num, den]}
    return {"key": name, "formula": formula, "value": num["value"] / den["value"], "unit": unit, "inputs": [num, den]}


def compute_ratios(
    statements: dict, price: Decimal | None = None, price_date: date | None = None, price_currency: str | None = None
) -> list[dict]:
    """Deterministic ratios for the latest period that has the inputs. Inputs are listed with their sources."""
    lines = statements["lines"]
    out = []
    for end in statements["period_ends"][:1]:
        rev = _value_at(lines, "revenue", end)
        out.append(
            _ratio("gross_margin", "Gross profit ÷ revenue (same period)", _value_at(lines, "gross_profit", end), rev)
        )
        out.append(
            _ratio(
                "operating_margin",
                "Operating income ÷ revenue (same period)",
                _value_at(lines, "operating_income", end),
                rev,
            )
        )
        out.append(_ratio("net_margin", "Net income ÷ revenue (same period)", _value_at(lines, "net_income", end), rev))
        out.append(
            _ratio(
                "debt_to_equity",
                "Long-term debt ÷ shareholders' equity (same balance-sheet date)",
                _value_at(lines, "long_term_debt", end),
                _value_at(lines, "equity", end),
            )
        )
        if statements["period"] == "annual":
            out.append(
                _ratio(
                    "return_on_equity",
                    "Net income for the year ÷ shareholders' equity at year end (ending, not average, equity)",
                    _value_at(lines, "net_income", end),
                    _value_at(lines, "equity", end),
                )
            )
            eps = _value_at(lines, "eps_diluted", end)
            pe = {
                "key": "price_to_earnings",
                "unit": "multiple",
                "value": None,
                "inputs": [eps],
                "formula": "Last price ÷ diluted EPS of the latest fiscal year (both in the same currency)",
                "price": price,
                "price_date": price_date,
            }
            if eps and price is not None and eps["value"] > 0 and price_currency == eps["unit"].split("/")[0]:
                pe["value"] = price / eps["value"]
            out.append(pe)
        ocf, capex = _value_at(lines, "operating_cash_flow", end), _value_at(lines, "capex", end)
        fcf = None
        if ocf and capex and ocf["unit"] == capex["unit"]:
            fcf = ocf["value"] - capex["value"]
        out.append(
            {
                "key": "free_cash_flow",
                "formula": "Operating cash flow − capital expenditure (same period)",
                "value": fcf,
                "unit": ocf["unit"] if ocf else None,
                "inputs": [ocf, capex],
            }
        )
    return out
