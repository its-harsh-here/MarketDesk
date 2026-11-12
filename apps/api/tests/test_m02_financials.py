"""SEC XBRL normalization: period classification, no YTD mixing, restatement provenance, unit checks, malformed facts,
bank and IFRS templates, and deterministic ratios with documented inputs. Fixtures are fictitious companies."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from marketdesk.config import REPO_ROOT
from marketdesk.services.financials import classify_duration, compute_ratios, is_financial_company, normalize_statements

FIX = REPO_ROOT / "fixtures" / "sec"


def load(name):
    return json.loads((FIX / name).read_text())


def line(st, key):
    return next(x for x in st["lines"] if x["key"] == key)


def test_duration_classification():
    assert classify_duration(date(2024, 10, 1), date(2025, 9, 30)) == "annual"
    assert classify_duration(date(2024, 9, 29), date(2025, 9, 27)) == "annual"  # 52-week year
    assert classify_duration(date(2025, 4, 1), date(2025, 6, 30)) == "quarterly"
    assert classify_duration(date(2024, 10, 1), date(2025, 6, 30)) is None  # nine-month year-to-date
    assert classify_duration(date(2024, 10, 1), date(2025, 3, 31)) is None  # six-month year-to-date


def test_annual_lines_keep_source_provenance_and_flag_restatements():
    st = normalize_statements(load("companyfacts_industrial.json"), sic="3560", period="annual", max_periods=5)
    assert st["taxonomy"] == "us-gaap" and st["template"] == "industrial" and st["currency"] == "USD"
    rev = line(st, "revenue")["values"]
    assert [(v["end"], v["value"]) for v in rev] == [
        (date(2025, 9, 30), Decimal("1200")),
        (date(2024, 9, 30), Decimal("1000")),
    ]
    latest = rev[0]
    assert (latest["tag"], latest["unit"], latest["form"], latest["accession"]) == (
        "Revenues",
        "USD",
        "10-K",
        "0000000001-25-000010",
    )
    assert latest["start"] == date(2024, 10, 1) and latest["filed"] == date(2025, 11, 1)
    assert rev[1]["restated"] is False and len(rev[1]["prior"]) == 1  # repeated as a comparative, same value
    ni = line(st, "net_income")["values"]
    fy24 = next(v for v in ni if v["end"] == date(2024, 9, 30))
    assert fy24["value"] == Decimal("140") and fy24["restated"] is True  # later filing wins, earlier kept
    assert fy24["prior"][0]["value"] == Decimal("150")
    # malformed value skipped, never zero-filled; EUR fact kept out of the USD line's currency set
    assert all(v["value"] != 0 for v in ni)
    assert line(st, "eps_diluted")["values"][0]["unit"] == "USD/shares"
    assert line(st, "eps_diluted")["values"][0]["value"] == Decimal("1.8")


def test_quarterly_lines_never_include_year_to_date_values():
    st = normalize_statements(load("companyfacts_industrial.json"), sic="3560", period="quarterly", max_periods=8)
    rev = line(st, "revenue")["values"]
    assert [(v["start"], v["end"], v["value"]) for v in rev] == [
        (date(2025, 4, 1), date(2025, 6, 30), Decimal("300")),
        (date(2025, 1, 1), date(2025, 3, 31), Decimal("290")),
    ]
    assets = line(st, "total_assets")["values"]
    # Instants: the fiscal-year-end balance (10-K) is also the latest quarter-end balance; no start date.
    assert [(v["end"], v["form"]) for v in assets[:2]] == [(date(2025, 9, 30), "10-K"), (date(2025, 6, 30), "10-Q")]
    assert all(v["start"] is None for v in assets)
    assert line(st, "gross_profit")["status"] == "unavailable"  # only annual data exists: not derived


def test_bank_template_does_not_map_industrial_lines():
    st = normalize_statements(load("companyfacts_bank.json"), sic="6021", period="annual", max_periods=5)
    assert st["template"] == "financial" and is_financial_company("6021") and not is_financial_company("3560")
    assert line(st, "revenue")["status"] == "not_applicable" and line(st, "revenue")["values"] == []
    assert line(st, "net_income")["values"][0]["value"] == Decimal("200")


def test_ifrs_filer_uses_ifrs_tags():
    st = normalize_statements(load("companyfacts_ifrs.json"), sic="7371", period="annual", max_periods=5)
    assert st["taxonomy"] == "ifrs-full"
    assert line(st, "revenue")["values"][0]["tag"] == "Revenue"
    assert line(st, "net_income")["values"][0]["tag"] == "ProfitLoss"
    assert line(st, "equity")["values"][0]["value"] == Decimal("11000")


def test_malformed_payload_is_an_error_not_an_empty_success():
    with pytest.raises(ValueError):
        normalize_statements({"cik": 1}, sic=None, period="annual", max_periods=5)
    with pytest.raises(ValueError):
        normalize_statements(load("companyfacts_industrial.json"), sic=None, period="monthly", max_periods=5)


def test_ratios_document_inputs_and_require_matching_currency():
    st = normalize_statements(load("companyfacts_industrial.json"), sic="3560", period="annual", max_periods=5)
    ratios = {
        r["key"]: r for r in compute_ratios(st, price=Decimal("27"), price_date=date(2025, 11, 3), price_currency="USD")
    }
    assert ratios["gross_margin"]["value"] == Decimal("0.4")
    assert ratios["operating_margin"]["value"] == Decimal("0.2")
    assert ratios["net_margin"]["value"] == Decimal("0.15")
    assert ratios["debt_to_equity"]["value"] == Decimal("0.25")
    assert ratios["return_on_equity"]["value"] == Decimal("0.09") and "ending" in ratios["return_on_equity"]["formula"]
    assert ratios["price_to_earnings"]["value"] == Decimal("15") and ratios["price_to_earnings"]["price_date"] == date(
        2025, 11, 3
    )
    assert ratios["free_cash_flow"]["value"] == Decimal("200")
    assert ratios["gross_margin"]["inputs"][0]["accession"] == "0000000001-25-000010"
    other_ccy = {
        r["key"]: r
        for r in compute_ratios(st, price=Decimal("2000"), price_date=date(2025, 11, 3), price_currency="INR")
    }
    assert other_ccy["price_to_earnings"]["value"] is None  # price and EPS in different currencies: not computed


def test_slimmed_company_facts_give_identical_statements():
    from marketdesk.services.financials import slim_companyfacts

    for name, sic in (("companyfacts_industrial.json", "3560"), ("companyfacts_bank.json", "6021"),
                      ("companyfacts_ifrs.json", "7371")):  # fmt: skip
        full = load(name)
        slim = json.loads(json.dumps(slim_companyfacts(full)))  # as stored in and read back from the cache
        for period in ("annual", "quarterly"):
            a = normalize_statements(full, sic=sic, period=period, max_periods=8)
            b = normalize_statements(slim, sic=sic, period=period, max_periods=8)
            assert a == b
