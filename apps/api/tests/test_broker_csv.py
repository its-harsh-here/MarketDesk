"""Broker CSV presets (DECISIONS #72): Zerodha tradebook conversion (exchange suffix, partial fills combined at a
volume-weighted price, non-trade rows skipped), custom mappings (date formats, buy/sell words), validation, and the
end-to-end preview → commit through the canonical pipeline."""

from __future__ import annotations

import csv
import io
from decimal import Decimal as D

import pytest

from marketdesk.api.errors import AppError
from marketdesk.services import broker_csv as bc

ZERODHA = (
    "symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,"
    "order_execution_time\n"
    "RELIANCE,INE002A01018,2026-10-01,NSE,EQ,EQ,buy,false,6,1300.00,1,A1,2026-10-01T09:20:01\n"
    "RELIANCE,INE002A01018,2026-10-01,NSE,EQ,EQ,buy,false,4,1305.00,2,A1,2026-10-01T09:20:02\n"
    "TCS,INE467B01029,2026-10-03,BSE,EQ,EQ,sell,false,2,3100.50,3,B7,2026-10-03T10:00:00\n"
    "INFY,INE009A01021,2026-10-04,NSE,EQ,EQ,transfer,false,1,1500,4,C1,2026-10-04T10:00:00\n"
)


def rows(content: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(content.decode())))


def test_zerodha_tradebook_converts_and_combines_fills():
    out, notes = bc.convert(ZERODHA.encode(), bc.validate_mapping(bc.BUILTIN["zerodha_tradebook"]))
    r = rows(out)
    assert [(x["date"], x["type"], x["symbol"], x["quantity"]) for x in r] == [
        ("2026-10-01", "BUY", "RELIANCE.NS", "10"), ("2026-10-03", "SELL", "TCS.BO", "2")]  # fmt: skip
    assert D(r[0]["price"]) == D("1302.0000")  # (6×1300 + 4×1305) ÷ 10
    assert r[0]["fees"] == "0" and r[0]["currency"] == "INR" and "order A1" in r[0]["notes"]
    assert any("1 partial fill" in n for n in notes) and any("not a buy or sell" in n for n in notes)
    assert any("zero fees" in n for n in notes)


def test_custom_mapping_formats_and_validation():
    m = bc.validate_mapping({
        "name": "My broker", "columns": {"date": "Date", "type": "Side", "symbol": "Ticker", "quantity": "Qty",
                                         "price": "Rate", "fees": "Charges"},
        "buy_words": ["B", "Bought"], "sell_words": ["S"], "date_format": "%d/%m/%Y", "symbol_suffix": "ns",
    })  # fmt: skip
    text = 'Date,Side,Ticker,Qty,Rate,Charges\n05/10/2026,B,ITC,100,"1,250.50",20\n06/10/2026,X,ITC,1,1,0\n'
    out, notes = bc.convert(text.encode(), m)
    r = rows(out)
    assert len(r) == 1 and r[0]["date"] == "2026-10-05" and r[0]["symbol"] == "ITC.NS"
    assert r[0]["price"] == "1250.50" and r[0]["fees"] == "20" and any("skipped" in n for n in notes)
    with pytest.raises(AppError, match="Choose a column for: price"):
        bc.validate_mapping({"name": "x", "columns": {"date": "d", "type": "t", "symbol": "s", "quantity": "q"}})
    with pytest.raises(AppError, match="both buy and sell"):
        bc.validate_mapping({**m, "buy_words": ["b"], "sell_words": ["b"]})
    with pytest.raises(AppError, match="exchange column"):
        bc.validate_mapping({**m, "symbol_suffix": "exchange"})
    with pytest.raises(AppError, match="no column named Rate"):
        bc.convert(b"Date,Side,Ticker,Qty\n", m)


def test_mapping_crud_and_import_round_trip(api):
    listed = api.get("/api/portfolio/csv-mappings").json()
    assert listed["mappings"][0]["id"] == "zerodha_tradebook" and "price" in listed["required"]
    saved = api.post("/api/portfolio/csv-mappings", json={
        "name": "Sample broker", "columns": {"date": "When", "type": "Side", "symbol": "Code", "quantity": "Units",
                                             "price": "Px", "fees": "Fee"},
        "buy_words": ["purchase"], "sell_words": ["sale"], "date_format": "%d-%m-%Y"}).json()  # fmt: skip
    assert saved["id"] == "custom_sample_broker"
    dep = "date,type,symbol,quantity,price,fees,amount,currency,notes\n2026-01-02,DEPOSIT,,,,,50000,INR,seed\n"
    p = api.post("/api/portfolio/import/preview", files={"file": ("d.csv", dep.encode(), "text/csv")}).json()
    api.post(f"/api/portfolio/import/{p['token']}/commit")
    broker = "When,Side,Code,Units,Px,Fee\n03-01-2026,purchase,SX:AURORA,10,100,10\n05-01-2026,sale,SX:AURORA,5,130,5\n"
    prev = api.post("/api/portfolio/import/preview", params={"mapping": saved["id"]},
                    files={"file": ("b.csv", broker.encode(), "text/csv")}).json()  # fmt: skip
    assert prev["can_import"] and prev["ok_rows"] == 2 and prev["mapping"] == saved["id"]
    assert api.post(f"/api/portfolio/import/{prev['token']}/commit").json()["imported"] == 2
    again = api.post("/api/portfolio/import/preview", params={"mapping": saved["id"]},
                     files={"file": ("b.csv", broker.encode(), "text/csv")}).json()  # fmt: skip
    assert again["duplicate_rows"] == 2 and not again["can_import"]
    assert api.delete(f"/api/portfolio/csv-mappings/{saved['id']}").status_code == 204
    assert api.post("/api/portfolio/import/preview", params={"mapping": saved["id"]},
                    files={"file": ("b.csv", broker.encode(), "text/csv")}).status_code == 404  # fmt: skip
