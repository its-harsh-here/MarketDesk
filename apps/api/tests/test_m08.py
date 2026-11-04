"""M08: INR and USD accounts, FX conversions, base-currency overview, CSV, and preservation of the INR ledger."""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from marketdesk.services.ledger import LedgerEntry, TxnType, replay
from marketdesk.services.portfolio import fingerprint

D = Decimal


def post(api, **body):
    return api.post("/api/portfolio/transactions", json=body)


def fund_usd(api, *, day="2026-01-05", inr="84050", usd="1000", fees="50", rate="84"):
    assert post(api, type="DEPOSIT", effective_date="2026-01-02", amount=inr).status_code == 201
    r = post(
        api,
        type="FX",
        effective_date=day,
        currency="INR",
        counter_currency="USD",
        amount=str(D(inr) - D(fees)),
        counter_amount=usd,
        fees=fees,
        fx_rate=rate,
        fx_source="Sample Bank remittance",
        fx_time=f"{day}T10:30:00+05:30",
    )
    assert r.status_code == 201, r.text
    return r.json()


def summary(api, ccy="INR"):
    return api.get("/api/portfolio/summary", params={"currency": ccy}).json()


# --------------------------------------------------------------------------- pure ledger
def test_fx_legs_are_transfers_not_deposits():
    out = LedgerEntry("txn:2", TxnType.FX_OUT, date(2026, 1, 5), 2, amount=D("84000"), fees=D("50"))
    inr = replay([LedgerEntry("txn:1", TxnType.DEPOSIT, date(2026, 1, 2), 1, amount=D("100000")), out], "INR")
    assert inr.cash == D("15950") and inr.fx_out == D("84000") and inr.fees == D("50")
    assert inr.net_contributions == D("100000")  # converting is not a withdrawal
    usd = replay([LedgerEntry("txn:2", TxnType.FX_IN, date(2026, 1, 5), 2, amount=D("1000"))], "USD")
    assert usd.cash == D("1000") and usd.deposits == 0 and usd.fx_in == D("1000")


def test_existing_fingerprints_are_unchanged():
    """Duplicate detection for pre-M08 rows must keep working: non-FX fingerprints use the original formula."""
    old = hashlib.sha256("|".join(["2026-01-02", "DEPOSIT", "", "", "", "0", "1000", "", "", "INR", "x"]).encode())
    new = fingerprint(date(2026, 1, 2), "DEPOSIT", None, None, None, D("0"), D("1000"), None, None, "INR", "x")
    assert new == old.hexdigest()


# --------------------------------------------------------------------------- accounts and FX through the API
def test_usd_account_is_funded_by_an_explicit_conversion(api):
    fx = fund_usd(api)
    assert fx["cash_effect"] == "-84050" and fx["counter_amount"] == "1000"
    assert fx["effective_rate"] == "84"  # INR per USD actually obtained, before fees
    assert fx["fx_source"] == "Sample Bank remittance" and fx["fx_time"].startswith("2026-01-05T05:00:00")
    buy = post(
        api, type="BUY", effective_date="2026-01-06", symbol="SX:HALCYON", quantity="5", price="160", fees="1",
        currency="USD",
    )  # fmt: skip
    assert buy.status_code == 201 and buy.json()["currency"] == "USD"
    inr, usd = summary(api, "INR"), summary(api, "USD")
    assert inr["currency"] == "INR" and inr["cash"] == "0" and inr["holdings"] == [] and inr["fx_out"] == "84000"
    assert inr["net_contributions"] == "84050"
    assert usd["currency"] == "USD" and usd["cash"] == "199" and usd["fx_in"] == "1000"
    assert usd["deposits"] == "0" and usd["net_contributions"] == "0"  # converted money is not a USD deposit
    h = usd["holdings"][0]
    assert h["symbol"] == "SX:HALCYON" and h["cost_basis"] == "801" and h["last_price"] == "171.37"
    # the transaction list never relabels: USD rows stay USD
    rows = api.get("/api/portfolio/transactions", params={"currency": "USD"}).json()["items"]
    assert {(r["type"], r["currency"]) for r in rows} == {("BUY", "USD"), ("FX", "INR")}


@pytest.mark.parametrize(
    "patch,field,text",
    [
        ({"counter_currency": "INR"}, "counter_currency", "different from INR"),
        ({"fx_source": "  "}, "fx_source", "source of the rate"),
        ({"fx_rate": "90"}, "fx_rate", "implies USD 933.33"),
        ({"counter_amount": None}, "counter_amount", "amount received"),
        ({"symbol": "SX:AURORA"}, "symbol", "do not reference an instrument"),
    ],
)
def test_fx_validation(api, patch, field, text):
    post(api, type="DEPOSIT", effective_date="2026-01-02", amount="100000")
    body = dict(
        type="FX", effective_date="2026-01-05", currency="INR", counter_currency="USD", amount="84000",
        counter_amount="1000", fx_rate="84", fx_source="Bank",
    )  # fmt: skip
    r = post(api, **{**body, **patch})
    assert r.status_code == 422, r.text
    assert text in r.json()["error"]["message"]
    assert r.json()["error"]["details"]["fields"][0]["field"] == field


def test_cross_account_replay_rejects_invalid_histories(api):
    fund_usd(api, day="2026-01-05")
    # a USD purchase dated before the conversion has no USD cash
    early = post(
        api, type="BUY", effective_date="2026-01-03", symbol="SX:HALCYON", quantity="1", price="10", currency="USD"
    )
    assert early.status_code == 422 and "would make USD cash negative" in early.json()["error"]["message"]
    # converting more INR than the account holds
    over = post(
        api, type="FX", effective_date="2026-01-06", currency="INR", counter_currency="USD", amount="1",
        counter_amount="0.01", fx_source="Bank",
    )  # fmt: skip
    assert over.status_code == 422 and "would make INR cash negative" in over.json()["error"]["message"]
    buy = post(
        api, type="BUY", effective_date="2026-01-06", symbol="SX:HALCYON", quantity="5", price="160", currency="USD"
    )
    assert buy.status_code == 201
    fx_id = api.get("/api/portfolio/transactions", params={"type": "FX"}).json()["items"][0]["id"]
    # deleting the conversion that funded the purchase would break the USD account
    d = api.delete(f"/api/portfolio/transactions/{fx_id}")
    assert d.status_code == 422 and "USD cash negative" in d.json()["error"]["message"]
    # an edit that receives less USD than was spent is rejected too
    smaller = api.put(
        f"/api/portfolio/transactions/{fx_id}",
        json=dict(
            type="FX", effective_date="2026-01-05", currency="INR", counter_currency="USD", amount="8400",
            counter_amount="100", fees="50", fx_source="Bank",
        ),
    )  # fmt: skip
    assert smaller.status_code == 422 and "USD cash negative" in smaller.json()["error"]["message"]


def test_overview_converts_for_display_and_withholds_totals_without_a_rate(api, monkeypatch):
    fund_usd(api)
    post(api, type="DEPOSIT", effective_date="2026-01-07", amount="5000")
    post(api, type="BUY", effective_date="2026-01-06", symbol="SX:HALCYON", quantity="5", price="160", currency="USD")
    ov = api.get("/api/portfolio/overview").json()
    assert ov["base_currency"] == "INR" and ov["complete"] is True and ov["incomplete_reasons"] == []
    acc = {a["currency"]: a for a in ov["accounts"]}
    usd = acc["USD"]
    assert usd["rate"]["pair"] == "USD/INR" and usd["rate"]["rate"] == "91.37" and usd["rate"]["status"] == "sample"
    assert usd["total_equity"] == str(D("200") + 5 * D("171.37"))
    assert D(usd["value_in_base"]) == (D(usd["total_equity"]) * D("91.37")).quantize(D("0.01"))
    assert acc["INR"]["value_in_base"] == acc["INR"]["total_equity"] == "5000"
    assert D(ov["total_in_base"]) == D(usd["value_in_base"]) + D("5000")
    assert "no historical rate" in ov["note"]
    # the account's own figures are unchanged by the display conversion
    assert summary(api, "USD")["total_equity"] == usd["total_equity"]

    from marketdesk.services import fx

    monkeypatch.setattr(fx, "fx_symbol", lambda source, base, quote: None)
    ov = api.get("/api/portfolio/overview").json()
    assert ov["complete"] is False and ov["total_in_base"] is None
    assert any("No usable USD/INR valuation rate" in r for r in ov["incomplete_reasons"])
    acc = {a["currency"]: a for a in ov["accounts"]}
    assert acc["USD"]["value_in_base"] is None and acc["USD"]["total_equity"] is not None  # native value still shown
    assert ov["partial_in_base"] == "5000"  # what can be converted, labelled partial


def test_only_inr_account_needs_no_rate(api):
    post(api, type="DEPOSIT", effective_date="2026-01-02", amount="1000")
    ov = api.get("/api/portfolio/overview").json()
    assert [a["currency"] for a in ov["accounts"]] == ["INR"] and ov["complete"] and ov["total_in_base"] == "1000"
    assert ov["accounts"][0]["rate"]["status"] == "identity"


# --------------------------------------------------------------------------- CSV
def upload(api, text: str):
    return api.post("/api/portfolio/import/preview", files={"file": ("t.csv", text.encode(), "text/csv")})


def test_csv_imports_both_accounts_and_round_trips(api):
    text = (
        "date,type,symbol,quantity,price,fees,amount,currency,counter_currency,counter_amount,fx_rate,fx_source,notes\n"
        "2026-01-02,DEPOSIT,,,,,100000,INR,,,,,\n"
        "2026-01-05,FX,,,,50,84000,INR,USD,1000,84,Sample Bank,\n"
        "2026-01-06,BUY,SX:HALCYON,5,160,1,,USD,,,,,\n"
        "2026-01-06,BUY,SX:HALCYON,1,160,0,,INR,,,,,\n"
    )
    p = upload(api, text).json()
    assert p["error_rows"] == 1 and "Record it in the USD account" in p["rows"][3]["messages"][0]
    p = upload(api, text.rsplit("\n", 2)[0] + "\n").json()
    assert p["can_import"], p
    assert api.post(f"/api/portfolio/import/{p['token']}/commit").json()["imported"] == 3
    assert summary(api, "USD")["cash"] == "199" and summary(api, "INR")["cash"] == "15950"
    body = api.get("/api/portfolio/export/transactions.csv").text
    rows = list(csv.DictReader(io.StringIO(body)))
    fx = next(r for r in rows if r["type"] == "FX")
    assert (fx["currency"], fx["counter_currency"], fx["counter_amount"], fx["fx_source"]) == (
        "INR", "USD", "1000", "Sample Bank",
    )  # fmt: skip
    again = upload(api, body).json()
    assert again["duplicate_rows"] == 3 and again["error_rows"] == 0
    hold = list(csv.reader(io.StringIO(api.get("/api/portfolio/export/holdings.csv?currency=USD").text)))
    assert hold[1][0] == "SX:HALCYON" and hold[1][-1] == "USD" and hold[-1][-1] == "USD"


def test_csv_fx_rows_are_validated(api):
    text = (
        "date,type,amount,currency,counter_currency,counter_amount,fx_source\n"
        "2026-01-05,FX,100,INR,INR,1,Bank\n"
        "2026-01-05,FX,100,INR,USD,1,\n"
        "2026-01-05,DEPOSIT,100,INR,USD,,\n"
    )
    msgs = [" ".join(r["messages"]) for r in upload(api, text).json()["rows"]]
    assert "different from INR" in msgs[0] and "source of the rate" in msgs[1] and "FX rows only" in msgs[2]


# --------------------------------------------------------------------------- data migration
def test_inr_ledger_survives_migration_0005_unchanged(tmp_path):
    """A pre-M08 (0004) backup with INR history restores, migrates, and reads back identically."""
    from marketdesk.api.app import create_app
    from marketdesk.cli import restore_with_migrations
    from marketdesk.db import get_engine
    from tests.conftest import Api, as_revision, make_settings, migrated

    src = migrated(make_settings(tmp_path / "src", marketdesk_env="development", dev_auth_bypass=True))
    with TestClient(create_app(src)) as c:
        api = Api(c)
        api.refresh_csrf()
        for t in (
            dict(type="DEPOSIT", effective_date="2026-01-02", amount="10000"),
            dict(type="BUY", effective_date="2026-01-03", symbol="SX:AURORA", quantity="10", price="100", fees="10"),
            dict(type="BUY", effective_date="2026-01-04", symbol="SX:AURORA", quantity="10", price="120", fees="10"),
            dict(type="SELL", effective_date="2026-01-05", symbol="SX:AURORA", quantity="5", price="130", fees="5"),
        ):
            assert post(api, **t).status_code == 201
        before_txns = api.get("/api/portfolio/transactions").json()["items"]
        before = summary(api)
        data = api.get("/api/backup/export").json()
    old = as_revision(data, "0004", tmp_path / "rev")
    assert "counter_currency" not in old["tables"]["ledger_transactions"]["columns"]
    dst = make_settings(
        tmp_path / "dst",
        marketdesk_env="development",
        dev_auth_bypass=True,
        database_url=f"sqlite:///{tmp_path}/dst.db",
    )
    app = create_app(dst)
    restore_with_migrations(dst.effective_database_url, get_engine(), old)
    with TestClient(app) as c:
        api = Api(c)
        after = summary(api)
        assert after == before  # acceptance arithmetic: cash 8425, basis 1665, realized 90, all unchanged
        assert after["cash"] == "8425" and after["realized_pnl"] == "90"
        assert api.get("/api/portfolio/transactions").json()["items"] == before_txns
        assert summary(api, "USD")["has_transactions"] is False
