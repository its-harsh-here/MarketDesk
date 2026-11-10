"""Currency converter: sample USD/INR, inverse pair, identity, unsupported currencies, validation."""

from __future__ import annotations


def test_convert_on_sample_data(api):
    a = api.get("/api/terminal/convert", params={"amount": "100", "from": "USD", "to": "INR"}).json()
    rate = float(a["rate"])
    assert rate > 1 and abs(float(a["result"]) - round(100 * rate, 2)) < 0.006 and a["inverted"] is False
    # INR→USD has no sample pair (and would be a small rate anyway): it comes from the USD/INR quote, inverted
    b = api.get("/api/terminal/convert", params={"amount": "1000", "from": "INR", "to": "USD"}).json()
    assert b["inverted"] is True and abs(float(b["rate"]) * rate - 1) < 1e-6 and "reverse pair" in b["note"]
    same = api.get("/api/terminal/convert", params={"amount": "5", "from": "INR", "to": "INR"}).json()
    assert float(same["result"]) == 5 and same["status"] == "identity"
    bad = api.get("/api/terminal/convert", params={"from": "USD", "to": "EUR"}).json()
    assert bad["status"] == "unsupported" and bad["currencies"] == ["INR", "USD"]
    assert api.get("/api/terminal/convert", params={"amount": "-1", "from": "USD", "to": "INR"}).status_code == 422
    assert api.get("/api/terminal/convert", params={"from": "usd", "to": "INR"}).status_code == 422
