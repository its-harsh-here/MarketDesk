"""Broker CSV presets: convert a broker's trade export into MarketDesk's canonical CSV, which then goes through the
same preview, validation, duplicate detection and atomic commit as any import (DECISIONS #72).

A mapping names the broker's column for each canonical field, the words meaning buy and sell, the date format,
how a symbol becomes a listing (Zerodha "RELIANCE" on NSE → "RELIANCE.NS"), and whether fills of one order are
combined (quantity summed, price volume-weighted) so partial fills of one order are not mistaken for duplicates.
Brokerage charges are usually not in trade exports; they import as zero fees and the preview says so.

Built-in presets cover formats whose columns are published; any other broker can be described once and saved.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.models import AppSetting
from marketdesk.services.csv_io import COLUMNS, safe_cell

FIELDS = ("date", "type", "symbol", "quantity", "price", "fees", "exchange", "order_id", "currency")
REQUIRED_FIELDS = ("date", "type", "symbol", "quantity", "price")
SUFFIXES = {"none": "", "ns": ".NS", "bo": ".BO", "exchange": None}
DATE_FORMATS = ("auto", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y", "%Y%m%d")
MAX_MAPPINGS = 20
_KEY = "csv_mappings"

BUILTIN: dict[str, dict] = {
    "zerodha_tradebook": {
        "name": "Zerodha Console — tradebook (equity)",
        "builtin": True,
        "columns": {
            "date": "trade_date",
            "type": "trade_type",
            "symbol": "symbol",
            "quantity": "quantity",
            "price": "price",
            "exchange": "exchange",
            "order_id": "order_id",
        },
        "buy_words": ["buy"],
        "sell_words": ["sell"],
        "date_format": "%Y-%m-%d",
        "symbol_suffix": "exchange",
        "currency": "INR",
        "combine_fills": True,
        "note": "Console → Reports → Tradebook → Equity, downloaded as CSV. Charges are not in the tradebook.",
    },  # fmt: skip
}


def _clean_words(words) -> list[str]:
    out = [str(w).strip().lower() for w in (words or []) if str(w).strip()]
    return out[:10]


def validate_mapping(m: dict) -> dict:
    """Normalise a user-supplied mapping; raises 422 with a precise reason."""
    if not isinstance(m, dict):
        raise AppError(422, "validation_error", "A mapping must be an object.")
    name = str(m.get("name") or "").strip()[:60]
    if not name:
        raise AppError(422, "validation_error", "Give the mapping a name.")
    cols = m.get("columns") or {}
    if not isinstance(cols, dict):
        raise AppError(422, "validation_error", "columns must map MarketDesk fields to your file's column names.")
    columns = {f: str(cols[f]).strip()[:80] for f in FIELDS if cols.get(f) and str(cols[f]).strip()}
    missing = [f for f in REQUIRED_FIELDS if f not in columns]
    if missing:
        raise AppError(422, "validation_error", f"Choose a column for: {', '.join(missing)}.")
    buy, sell = _clean_words(m.get("buy_words") or ["buy"]), _clean_words(m.get("sell_words") or ["sell"])
    if set(buy) & set(sell):
        raise AppError(422, "validation_error", "A word cannot mean both buy and sell.")
    fmt = m.get("date_format") or "auto"
    if fmt not in DATE_FORMATS:
        raise AppError(422, "validation_error", f"Date format must be one of {', '.join(DATE_FORMATS)}.")
    suffix = m.get("symbol_suffix") or "none"
    if suffix not in SUFFIXES:
        raise AppError(422, "validation_error", "symbol_suffix must be none, ns, bo or exchange.")
    if suffix == "exchange" and "exchange" not in columns:
        raise AppError(422, "validation_error", "Choose the exchange column to add the exchange suffix.")
    currency = str(m.get("currency") or "INR").upper()
    if currency not in ("INR", "USD"):
        raise AppError(422, "validation_error", "Currency must be INR or USD.")
    return {"name": name, "columns": columns, "buy_words": buy, "sell_words": sell, "date_format": fmt,
            "symbol_suffix": suffix, "currency": currency, "combine_fills": bool(m.get("combine_fills"))}  # fmt: skip


def saved_mappings(db: Session) -> dict[str, dict]:
    row = db.get(AppSetting, _KEY)
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


def all_mappings(db: Session) -> list[dict]:
    out = [{"id": k, **v} for k, v in BUILTIN.items()]
    out += [{"id": k, **v, "builtin": False} for k, v in sorted(saved_mappings(db).items())]
    return out


def save_mapping(db: Session, mapping: dict) -> dict:
    m = validate_mapping(mapping)
    current = saved_mappings(db)
    mid = "custom_" + re.sub(r"[^a-z0-9]+", "_", m["name"].lower()).strip("_")[:40]
    if mid not in current and len(current) >= MAX_MAPPINGS:
        raise AppError(422, "validation_error", f"Up to {MAX_MAPPINGS} saved mappings.")
    current[mid] = m
    row = db.get(AppSetting, _KEY)
    if row is None:
        db.add(AppSetting(key=_KEY, value=current))
    else:
        row.value = current
    db.commit()
    return {"id": mid, **m, "builtin": False}


def delete_mapping(db: Session, mid: str) -> None:
    current = saved_mappings(db)
    if mid not in current:
        raise AppError(404, "not_found", "No such saved mapping.")
    del current[mid]
    row = db.scalar(select(AppSetting).where(AppSetting.key == _KEY))
    row.value = current
    db.commit()


def get_mapping(db: Session, mid: str) -> dict:
    if mid in BUILTIN:
        return validate_mapping(BUILTIN[mid])
    saved = saved_mappings(db)
    if mid not in saved:
        raise AppError(404, "not_found", "No such mapping.")
    return validate_mapping(saved[mid])


def _date(raw: str, fmt: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    s = s.split("T")[0].split(" ")[0] if fmt in ("auto", "%Y-%m-%d") else s
    formats = DATE_FORMATS[1:] if fmt == "auto" else (fmt,)
    for f in formats:
        try:
            return datetime.strptime(s, f).date().isoformat()  # noqa: DTZ007 (a calendar date, no time zone)
        except ValueError:
            continue
    return None


def _dec(raw: str) -> Decimal | None:
    s = (raw or "").strip().replace(",", "")
    try:
        return Decimal(s) if s else None
    except InvalidOperation:
        return None


def _symbol(raw: str, exchange: str, suffix: str) -> str:
    sym = (raw or "").strip().upper()
    if not sym or "." in sym or ":" in sym:
        return sym
    if suffix == "exchange":
        ex = (exchange or "").strip().upper()
        return sym + {"NSE": ".NS", "BSE": ".BO"}.get(ex, "")
    return sym + (SUFFIXES.get(suffix) or "")


def convert(content: bytes, mapping: dict) -> tuple[bytes, list[str]]:
    """Broker CSV bytes → canonical CSV bytes, plus notes (rows skipped and why, fills combined)."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError(422, "invalid_encoding", "The file must be UTF-8 encoded CSV text.") from exc
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip() for h in (reader.fieldnames or [])]
    lookup = {h.lower(): h for h in header}
    cols = {f: lookup.get(c.lower()) for f, c in mapping["columns"].items()}
    absent = [mapping["columns"][f] for f, h in cols.items() if h is None]
    if absent:
        found = ", ".join(header)
        raise AppError(422, "validation_error", f"The file has no column named {', '.join(absent)}. Found: {found}.")
    notes: list[str] = []
    rows: list[dict] = []
    skipped: dict[str, int] = {}
    buy, sell = set(mapping["buy_words"]), set(mapping["sell_words"])

    def get(r: dict, f: str) -> str:
        h = cols.get(f)
        return (r.get(h) or "").strip() if h else ""

    for r in reader:
        r = {(k or "").strip(): v for k, v in r.items()}
        side = get(r, "type").lower()
        kind = "BUY" if side in buy else "SELL" if side in sell else None
        day = _date(get(r, "date"), mapping["date_format"])
        qty, price = _dec(get(r, "quantity")), _dec(get(r, "price"))
        if kind is None:
            skipped["not a buy or sell"] = skipped.get("not a buy or sell", 0) + 1
            continue
        if day is None or qty is None or price is None or qty <= 0 or price <= 0:
            skipped["missing or invalid date, quantity or price"] = skipped.get(
                "missing or invalid date, quantity or price", 0) + 1  # fmt: skip
            continue
        symbol = _symbol(get(r, "symbol"), get(r, "exchange"), mapping["symbol_suffix"])
        currency = (get(r, "currency") or mapping["currency"]).upper()
        rows.append({"date": day, "type": kind, "symbol": symbol, "quantity": qty, "price": price,
                     "fees": _dec(get(r, "fees")), "currency": currency, "order": get(r, "order_id")})  # fmt: skip

    if mapping.get("combine_fills"):
        grouped: dict[tuple, dict] = {}
        for x in rows:
            key = (x["order"], x["date"], x["type"], x["symbol"]) if x["order"] else (id(x),)
            g = grouped.get(key)
            if g is None:
                grouped[key] = {**x, "value": x["quantity"] * x["price"]}
            else:
                g["quantity"] += x["quantity"]
                g["value"] += x["quantity"] * x["price"]
                g["fees"] = (g["fees"] or 0) + (x["fees"] or 0) if (g["fees"] or x["fees"]) else None
                g["fills"] = g.get("fills", 1) + 1
        combined = sum(g.get("fills", 1) - 1 for g in grouped.values())
        rows = []
        for g in grouped.values():
            g["price"] = (g["value"] / g["quantity"]).quantize(Decimal("0.0001"))
            rows.append(g)
        if combined:
            notes.append(f"{combined} partial fill(s) were combined into their orders (volume-weighted price).")
    for why, n in skipped.items():
        notes.append(f"{n} row(s) skipped: {why}.")
    if rows and all(x["fees"] is None for x in rows):
        notes.append("This export has no charges column: trades import with zero fees; add brokerage separately.")

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(COLUMNS)
    for x in sorted(rows, key=lambda x: (x["date"], x["type"] != "BUY")):
        values = {"date": x["date"], "type": x["type"], "symbol": x["symbol"], "quantity": format(x["quantity"], "f"),
                  "price": format(x["price"], "f"), "fees": format(x["fees"], "f") if x["fees"] is not None else "0",
                  "currency": x["currency"], "notes": f"Imported via {mapping['name']}"
                  + (f" · order {x['order']}" if x.get("order") else "")}  # fmt: skip
        w.writerow([safe_cell(values.get(c, "")) for c in COLUMNS])
    return out.getvalue().encode("utf-8"), notes
