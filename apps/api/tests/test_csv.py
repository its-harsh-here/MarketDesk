"""CSV import preview/confirm, duplicate detection, malformed input, export safety."""

from __future__ import annotations

import csv
import io

GOOD = (
    "date,type,symbol,quantity,price,fees,amount,currency,notes\n"
    "2026-01-02,DEPOSIT,,,,,10000,INR,initial\n"
    "2026-01-03,BUY,SX:AURORA,10,100,10,,INR,\n"
    "2026-01-04,BUY,SX:AURORA,10,120,10,,INR,\n"
    "2026-01-05,SELL,SX:AURORA,5,130,5,,INR,\n"
)


def upload(api, content: str, name="ledger.csv", ctype="text/csv"):
    return api.post("/api/portfolio/import/preview", files={"file": (name, content.encode(), ctype)})


def test_preview_then_atomic_import_then_duplicate_rejected(api):
    p = upload(api, GOOD).json()
    assert p["can_import"] and p["ok_rows"] == 4 and p["error_rows"] == 0
    # nothing written until confirmation
    assert api.get("/api/portfolio/transactions").json()["total"] == 0
    c = api.post(f"/api/portfolio/import/{p['token']}/commit")
    assert c.status_code == 200 and c.json()["imported"] == 4
    assert api.get("/api/portfolio/summary").json()["cash"] == "8425"
    # committing the same preview twice is refused
    assert api.post(f"/api/portfolio/import/{p['token']}/commit").status_code == 409
    # uploading the same file again: all rows are duplicates, nothing to import
    again = upload(api, GOOD).json()
    assert again["duplicate_rows"] == 4 and not again["can_import"] and again["token"] is None
    assert api.get("/api/portfolio/transactions").json()["total"] == 4


def test_malformed_rows_are_reported_and_block_import(api):
    bad = (
        "date,type,symbol,quantity,price,fees,amount,currency,notes\n"
        "02/01/2026,DEPOSIT,,,,,10000,INR,\n"
        "2026-01-03,BUY,SX:AURORA,ten,100,0,,INR,\n"
        '2026-01-03,BUY,SX:AURORA,1,"1,000",0,,INR,\n'
        "2026-01-03,TRANSFER,,,,,5,INR,\n"
        "2026-01-03,BUY,SX:HALCYON,1,10,0,,INR,\n"
        "2026-01-03,DEPOSIT,,,,,5,USD,\n"
    )
    p = upload(api, bad).json()
    assert not p["can_import"] and p["error_rows"] == 6
    msgs = {r["row"]: " ".join(r["messages"]) for r in p["rows"]}
    assert "YYYY-MM-DD" in msgs[2]
    assert "not a number" in msgs[3]
    assert "thousands" in msgs[4]
    assert "type must be" in msgs[5]
    assert "INR-only" in msgs[6]
    assert "Only INR" in msgs[7]


def test_unknown_columns_and_file_type_rejected(api):
    p = upload(api, "date,type,price_usd\n2026-01-01,DEPOSIT,1\n").json()
    assert not p["can_import"] and "Unknown column" in p["header_errors"][0]
    assert upload(api, GOOD, name="ledger.xlsx").status_code == 415
    assert upload(api, "\xff\xfe".encode("latin-1").decode("latin-1") + GOOD).status_code in (200, 422)


def test_ledger_violation_in_file_points_to_row(api):
    content = (
        "date,type,symbol,quantity,price,fees,amount\n2026-01-02,DEPOSIT,,,,,100\n2026-01-03,BUY,SX:AURORA,2,60,,\n"
    )
    p = upload(api, content).json()
    assert not p["can_import"]
    assert p["ledger_error"]["ref"] == "csv:3"
    assert any(r["row"] == 3 and r["status"] == "error" for r in p["rows"])


def test_export_defends_against_formula_injection_and_round_trips(api):
    api.post(
        "/api/portfolio/transactions",
        json={"type": "DEPOSIT", "effective_date": "2026-01-02", "amount": "1000", "notes": '=HYPERLINK("http://x")'},
    )
    api.post(
        "/api/portfolio/transactions",
        json={
            "type": "BUY",
            "effective_date": "2026-01-03",
            "symbol": "SX:AURORA",
            "quantity": "2",
            "price": "100",
            "notes": "@SUM(A1)",
        },
    )
    body = api.get("/api/portfolio/export/transactions.csv").text
    rows = list(csv.reader(io.StringIO(body)))
    assert rows[1][-1].startswith("'=")
    assert rows[2][-1].startswith("'@")
    hold = list(csv.reader(io.StringIO(api.get("/api/portfolio/export/holdings.csv").text)))
    assert hold[1][0] == "SX:AURORA" and hold[-1][0] == "CASH"
    # the exported file is recognised as duplicates when re-imported (round trip)
    p = upload(api, body).json()
    assert p["duplicate_rows"] == 2 and p["error_rows"] == 0
