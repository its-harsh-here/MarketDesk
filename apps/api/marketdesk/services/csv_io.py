"""Canonical CSV import (preview → confirm, atomic, duplicate-safe) and export.

Canonical columns (header row required, order free, unknown columns rejected):
    date,type,symbol,quantity,price,fees,amount,currency,split_from,split_to,
    counter_currency,counter_amount,fx_rate,fx_source,fx_time,notes
- date: YYYY-MM-DD (effective trading/settlement date)
- type: DEPOSIT | WITHDRAWAL | BUY | SELL | DIVIDEND | SPLIT | FX
- numbers: plain decimals with '.' and no thousands separators
- currency: the account, INR or USD (blank means INR); an instrument must trade in its row's currency
- FX rows: amount + fees leave `currency`, counter_amount arrives in counter_currency; fx_source is required,
  fx_rate (quoted) and fx_time (ISO 8601, UTC if no offset) are optional
- SPLIT rows in a file count as explicit confirmation of that split.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import secrets
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.config import Settings
from marketdesk.models import ImportBatch, LedgerTransaction
from marketdesk.services.instruments import resolve_instrument
from marketdesk.services.ledger import CURRENCIES, LedgerEntry, LedgerError, TxnType, validate_entry
from marketdesk.services.market import MarketDataService
from marketdesk.services.portfolio import (
    LEDGER_LOCK,
    _prepare_fx,
    account_entries,
    all_transactions,
    ensure_portfolio_instrument,
    fingerprint,
    replay_accounts,
    txn_dict,
)

COLUMNS = [
    "date",
    "type",
    "symbol",
    "quantity",
    "price",
    "fees",
    "amount",
    "currency",
    "split_from",
    "split_to",
    "counter_currency",
    "counter_amount",
    "fx_rate",
    "fx_source",
    "fx_time",
    "notes",
]
REQUIRED = {"date", "type"}
NUMERIC = ("quantity", "price", "fees", "amount", "split_from", "split_to", "counter_amount", "fx_rate")
STORED_TYPES = ("DEPOSIT", "WITHDRAWAL", "BUY", "SELL", "DIVIDEND", "SPLIT", "FX")
_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")
_NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")
TOKEN_TTL = timedelta(hours=2)


def safe_cell(value: object) -> str:
    """Neutralise spreadsheet formula injection while keeping plain numbers numeric."""
    if value is None:
        return ""
    s = str(value)
    if _NUMERIC_RE.match(s):
        return s
    if s.startswith(_DANGEROUS):
        return "'" + s
    return s


def _unescape(s: str) -> str:
    if len(s) > 1 and s[0] == "'" and s[1] in "=+-@\t\r":
        return s[1:]
    return s


@dataclass
class ParsedRow:
    row: int
    raw: dict[str, str | None]
    errors: list[str] = field(default_factory=list)
    type: str | None = None
    effective_date: date | None = None
    symbol: str | None = None
    values: dict[str, Decimal | None] = field(default_factory=dict)
    currency: str = "INR"
    notes: str | None = None
    fingerprint: str | None = None
    duplicate: bool = False
    counter_currency: str | None = None
    fx_source: str | None = None
    fx_time: datetime | None = None


def parse_csv(content: bytes, settings: Settings) -> tuple[list[ParsedRow], list[str]]:
    if len(content) > settings.max_upload_bytes:
        raise AppError(413, "payload_too_large", f"CSV files are limited to {settings.max_upload_bytes // 1000} KB.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError(422, "invalid_encoding", "The file must be UTF-8 encoded CSV text.") from exc
    if "\x00" in text:
        raise AppError(415, "unsupported_media_type", "The file does not look like CSV text.")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return [], ["The file is empty."]
    header = [h.strip().lower() for h in header]
    header_errors: list[str] = []
    unknown = [h for h in header if h not in COLUMNS]
    if unknown:
        header_errors.append(f"Unknown column(s): {', '.join(unknown)}. Expected: {', '.join(COLUMNS)}.")
    missing = REQUIRED - set(header)
    if missing:
        header_errors.append(f"Missing required column(s): {', '.join(sorted(missing))}.")
    if len(set(header)) != len(header):
        header_errors.append("Duplicate column names.")
    if header_errors:
        return [], header_errors

    rows: list[ParsedRow] = []
    for line_no, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue
        if len(rows) >= settings.max_import_rows:
            header_errors.append(f"Only the first {settings.max_import_rows} rows can be imported at once.")
            break
        raw: dict[str, str | None] = {c: None for c in COLUMNS}
        pr = ParsedRow(row=line_no, raw=raw)
        if len(cells) != len(header):
            pr.errors.append(f"Expected {len(header)} cells but found {len(cells)}.")
        for h, c in zip(header, cells, strict=False):
            raw[h] = _unescape(c.strip()) or None
        _parse_row(pr)
        rows.append(pr)
    return rows, header_errors


def _parse_row(pr: ParsedRow) -> None:
    raw = pr.raw
    try:
        pr.effective_date = date.fromisoformat(raw["date"] or "")
    except ValueError:
        pr.errors.append("date must use YYYY-MM-DD.")
    t = (raw["type"] or "").upper()
    if t not in STORED_TYPES:
        pr.errors.append(f"type must be one of {', '.join(STORED_TYPES)}.")
    else:
        pr.type = t
    for col in NUMERIC:
        v = raw[col]
        if v is None:
            pr.values[col] = None
            continue
        if "," in v:
            pr.errors.append(f"{col} must not contain thousands separators.")
            continue
        try:
            d = Decimal(v)
            if not d.is_finite():
                raise InvalidOperation
            pr.values[col] = d
        except InvalidOperation:
            pr.errors.append(f"{col} is not a number.")
    ccy = (raw["currency"] or "INR").upper()
    if ccy not in CURRENCIES:
        pr.errors.append(f"currency must be {' or '.join(CURRENCIES)} (the account); amounts are never relabeled.")
    pr.currency = ccy
    pr.counter_currency = (raw["counter_currency"] or "").upper() or None
    pr.fx_source = raw["fx_source"]
    if raw["fx_time"]:
        try:
            ft = datetime.fromisoformat(raw["fx_time"])
            pr.fx_time = ft if ft.tzinfo else ft.replace(tzinfo=UTC)
        except ValueError:
            pr.errors.append("fx_time must be an ISO 8601 date-time.")
    if t != "FX" and any(raw[c] for c in ("counter_currency", "counter_amount", "fx_rate", "fx_source", "fx_time")):
        pr.errors.append("counter_currency, counter_amount, fx_rate, fx_source and fx_time apply to FX rows only.")
    sym = (raw["symbol"] or "").strip().upper() or None
    pr.symbol = sym
    notes = raw["notes"]
    if notes and len(notes) > 500:
        pr.errors.append("notes must be at most 500 characters.")
    pr.notes = notes
    if pr.type in ("BUY", "SELL", "DIVIDEND", "SPLIT") and not sym:
        pr.errors.append("symbol is required for this type.")
    if pr.type in ("DEPOSIT", "WITHDRAWAL", "FX") and sym:
        pr.errors.append(f"{pr.type} must not have a symbol.")


def _fx_payload(pr: ParsedRow) -> dict:
    v = pr.values
    return {
        "effective_date": pr.effective_date,
        "currency": pr.currency,
        "counter_currency": pr.counter_currency,
        "amount": v.get("amount"),
        "counter_amount": v.get("counter_amount"),
        "fx_rate": v.get("fx_rate"),
        "fees": v.get("fees"),
        "fx_source": pr.fx_source,
        "fx_time": pr.fx_time,
        **{k: v.get(k) for k in ("quantity", "price", "split_from", "split_to")},
    }


def _legs(pr: ParsedRow, symbol: str | None) -> dict[str, list[LedgerEntry]]:
    """The row's ledger entries per currency account (an FX row has a paying and a receiving leg)."""
    if pr.type != "FX":
        return {pr.currency: [_entry(pr, symbol)]}
    v = pr.values
    out = LedgerEntry(
        ref=f"csv:{pr.row}",
        type=TxnType.FX_OUT,
        effective_date=pr.effective_date,
        seq=10**8 + pr.row,
        amount=v.get("amount"),
        fees=v.get("fees") or Decimal(0),
        label=f"FX {pr.currency}→{pr.counter_currency} on {pr.effective_date.isoformat()} (CSV row {pr.row})",
    )
    return {
        pr.currency: [out],
        pr.counter_currency: [replace(out, type=TxnType.FX_IN, amount=v.get("counter_amount"), fees=Decimal(0))],
    }


def _entry(pr: ParsedRow, symbol: str | None) -> LedgerEntry:
    v = pr.values
    t = TxnType(pr.type)
    return LedgerEntry(
        ref=f"csv:{pr.row}",
        type=t,
        effective_date=pr.effective_date,
        seq=10**8 + pr.row,
        symbol=symbol,
        quantity=v.get("quantity") if t in (TxnType.BUY, TxnType.SELL) else None,
        price=v.get("price") if t in (TxnType.BUY, TxnType.SELL) else None,
        fees=v.get("fees") or Decimal(0),
        amount=v.get("amount") if t in (TxnType.DEPOSIT, TxnType.WITHDRAWAL, TxnType.DIVIDEND) else None,
        split_from=v.get("split_from") if t == TxnType.SPLIT else None,
        split_to=v.get("split_to") if t == TxnType.SPLIT else None,
        label=f"{t.value}{' ' + symbol if symbol else ''} on {pr.effective_date.isoformat()} (CSV row {pr.row})",
    )


async def build_preview(
    db: Session, settings: Settings, market: MarketDataService, filename: str | None, content: bytes
) -> dict:
    rows, header_errors = parse_csv(content, settings)
    symbols: dict[str, str] = {}
    insts: dict = {}
    unique_syms = {r.symbol for r in rows if r.symbol and not r.errors}
    if len(unique_syms) > settings.max_symbols_per_request:
        header_errors.append(f"At most {settings.max_symbols_per_request} distinct symbols per import.")
    else:
        for sym in sorted(unique_syms):
            try:
                inst = await resolve_instrument(db, market, sym)
                ensure_portfolio_instrument(inst)
                symbols[sym], insts[sym] = inst.symbol, inst
            except AppError as err:
                for r in rows:
                    if r.symbol == sym:
                        r.errors.append(err.message)
    for r in rows:  # each row's instrument must trade in that row's account currency
        inst = insts.get(r.symbol) if r.symbol else None
        if inst is not None and not r.errors:
            try:
                ensure_portfolio_instrument(inst, r.currency)
            except AppError as err:
                r.errors.append(err.message)

    existing = all_transactions(db)
    seen = {t.fingerprint for t in existing}
    for r in rows:
        if r.errors:
            continue
        sym = symbols.get(r.symbol) if r.symbol else None
        extra: tuple = ()
        if r.type == "FX":
            try:
                fx = _prepare_fx(_fx_payload(r), r.notes)
            except AppError as err:
                r.errors.append(err.message)
                continue
            entry = _legs(r, None)[r.currency][0]
            extra = (fx.counter_currency, fx.counter_amount, fx.fx_rate, fx.fx_source)
        else:
            entry = _entry(r, sym)
        try:
            for legs in _legs(r, sym).values():
                for leg in legs:
                    validate_entry(leg)
        except LedgerError as err:
            r.errors.append(err.message)
            continue
        r.fingerprint = fingerprint(
            r.effective_date,
            r.type,
            sym,
            entry.quantity,
            entry.price,
            entry.fees,
            entry.amount,
            entry.split_from,
            entry.split_to,
            r.currency,
            r.notes,
            extra,
        )
        if r.fingerprint in seen:
            r.duplicate = True
        else:
            seen.add(r.fingerprint)

    ledger_error = None
    new_rows = [r for r in rows if not r.errors and not r.duplicate]
    error_rows = [r for r in rows if r.errors]
    if not error_rows and new_rows and not header_errors:
        entries = account_entries(existing)
        for r in new_rows:
            for ccy, legs in _legs(r, symbols.get(r.symbol) if r.symbol else None).items():
                entries.setdefault(ccy, []).extend(legs)
        try:
            replay_accounts(entries)
        except LedgerError as err:
            ledger_error = err.to_dict()
            if err.ref.startswith("csv:"):
                bad = next(r for r in rows if r.row == int(err.ref.split(":")[1]))
                bad.errors.append(err.message)
    error_rows = [r for r in rows if r.errors]
    blocking = None
    if header_errors:
        blocking = header_errors[0]
    elif error_rows:
        blocking = "Fix the rows marked as errors and upload the file again. Nothing has been imported."
    elif ledger_error:
        blocking = f"The ledger would become invalid: {ledger_error['message']}"
    elif not new_rows:
        blocking = "Every row already exists in the ledger; nothing new to import." if rows else "No data rows found."
    can_import = blocking is None

    token = None
    if can_import:
        token = secrets.token_urlsafe(24)
        db.add(
            ImportBatch(
                token=token,
                filename=(filename or "")[:200] or None,
                content_sha256=hashlib.sha256(content).hexdigest(),
                status="previewed",
                rows=[_row_payload(r, symbols) for r in new_rows],
                summary={"total": len(rows), "new": len(new_rows), "duplicates": sum(r.duplicate for r in rows)},
            )
        )
        db.commit()
    return {
        "token": token,
        "filename": filename,
        "total_rows": len(rows),
        "ok_rows": len(new_rows),
        "error_rows": len(error_rows),
        "duplicate_rows": sum(1 for r in rows if r.duplicate and not r.errors),
        "can_import": can_import,
        "blocking_reason": blocking,
        "ledger_error": ledger_error,
        "header_errors": header_errors,
        "rows": [
            {
                "row": r.row,
                "status": "error" if r.errors else ("duplicate" if r.duplicate else "ok"),
                "values": {k: r.raw.get(k) for k in COLUMNS},
                "messages": r.errors
                or (["Already in the ledger (or repeated in this file); will be skipped."] if r.duplicate else []),
            }
            for r in rows
        ],
    }


def _row_payload(r: ParsedRow, symbols: dict[str, str]) -> dict:
    return {
        "row": r.row,
        "type": r.type,
        "date": r.effective_date.isoformat(),
        "symbol": symbols.get(r.symbol) if r.symbol else None,
        **{k: (format(v, "f") if v is not None else None) for k, v in r.values.items()},
        "currency": r.currency,
        "counter_currency": r.counter_currency,
        "fx_source": r.fx_source.strip() if r.fx_source else None,
        "fx_time": r.fx_time.isoformat() if r.fx_time else None,
        "notes": r.notes,
        "fingerprint": r.fingerprint,
    }


async def commit_import(db: Session, market: MarketDataService, token: str) -> dict:
    batch = db.scalar(select(ImportBatch).where(ImportBatch.token == token))
    if batch is None:
        raise AppError(404, "not_found", "This import preview was not found. Upload the file again.")
    if batch.status == "committed":
        raise AppError(409, "already_imported", "This import was already committed; it will not be applied twice.")
    if datetime.now(UTC) - batch.created_at > TOKEN_TTL:
        raise AppError(410, "preview_expired", "This preview has expired. Upload the file again.")
    insts = {}
    for r in batch.rows:
        if r["symbol"] and r["symbol"] not in insts:
            insts[r["symbol"]] = await resolve_instrument(db, market, r["symbol"])
    with LEDGER_LOCK:
        existing = all_transactions(db)
        seen = {t.fingerprint for t in existing}
        new: list[LedgerTransaction] = []
        new_rows: list[int] = []
        skipped = 0
        for r in batch.rows:
            if r["fingerprint"] in seen:
                skipped += 1
                continue
            seen.add(r["fingerprint"])
            dec = {k: (Decimal(r[k]) if r.get(k) is not None else None) for k in NUMERIC}
            inst = insts.get(r["symbol"]) if r["symbol"] else None
            new.append(
                LedgerTransaction(
                    type=r["type"],
                    effective_date=date.fromisoformat(r["date"]),
                    instrument_id=inst.id if inst else None,
                    instrument=inst,
                    quantity=dec["quantity"],
                    price=dec["price"],
                    fees=dec["fees"] or Decimal(0),
                    amount=dec["amount"],
                    split_from=dec["split_from"],
                    split_to=dec["split_to"],
                    currency=r.get("currency") or "INR",
                    counter_currency=r.get("counter_currency"),
                    counter_amount=dec.get("counter_amount"),
                    fx_rate=dec.get("fx_rate"),
                    fx_source=r.get("fx_source"),
                    fx_time=datetime.fromisoformat(r["fx_time"]) if r.get("fx_time") else None,
                    notes=r["notes"],
                    fingerprint=r["fingerprint"],
                    source="import",
                    created_via="csv",
                    import_batch_id=batch.id,
                )
            )
            new_rows.append(r["row"])
        entries = account_entries(existing)
        for i, (t, row_no) in enumerate(zip(new, new_rows, strict=True)):
            for ccy, legs in account_entries([t]).items():
                entries.setdefault(ccy, []).extend(
                    replace(
                        leg,
                        ref=f"csv:{row_no}",
                        seq=10**8 + i,
                        label=f"{t.type} on {t.effective_date.isoformat()} (CSV row {row_no})",
                    )
                    for leg in legs
                )
        try:
            replay_accounts(entries)
        except LedgerError as err:
            raise AppError(
                422, "ledger_rejected", f"Import rejected: {err.message}", {"ledger_error": err.to_dict()}
            ) from err
        db.add_all(new)
        batch.status = "committed"
        batch.committed_at = datetime.now(UTC)
        db.commit()  # single atomic transaction for all rows
        return {"imported": len(new), "skipped_duplicates": skipped, "batch_id": batch.id}


def export_transactions_csv(db: Session) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    for t in all_transactions(db):
        d = txn_dict(t)
        w.writerow(
            [
                safe_cell(x)
                for x in (
                    t.effective_date.isoformat(),
                    t.type,
                    d["symbol"],
                    _plain(t.quantity),
                    _plain(t.price),
                    _plain(t.fees),
                    _plain(t.amount),
                    t.currency,
                    _plain(t.split_from),
                    _plain(t.split_to),
                    t.counter_currency,
                    _plain(t.counter_amount),
                    _plain(t.fx_rate),
                    t.fx_source,
                    t.fx_time.isoformat() if t.fx_time else None,
                    t.notes,
                )
            ]
        )
    return buf.getvalue()


def export_holdings_csv(summary: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(
        [
            "symbol",
            "name",
            "quantity",
            "average_cost",
            "cost_basis",
            "last_price",
            "market_value",
            "unrealized_pnl",
            "realized_pnl",
            "dividends",
            "mark_status",
            "mark_time",
            "currency",
        ]
    )
    for h in summary["holdings"]:
        w.writerow(
            [
                safe_cell(x)
                for x in (
                    h["symbol"],
                    h["name"],
                    _plain(h["quantity"]),
                    _plain(h["average_cost"], 4),
                    _plain(h["cost_basis"], 2),
                    _plain(h["last_price"]),
                    _plain(h["market_value"], 2),
                    _plain(h["unrealized_pnl"], 2),
                    _plain(h["realized_pnl"], 2),
                    _plain(h["dividends"], 2),
                    h["mark_status"],
                    h["mark_time"],
                    summary["currency"],
                )
            ]
        )
    w.writerow(
        [
            safe_cell(x)
            for x in (
                "CASH",
                "Cash balance",
                "",
                "",
                "",
                "",
                _plain(summary["cash"], 2),
                "",
                "",
                "",
                "",
                "",
                summary["currency"],
            )
        ]
    )
    return buf.getvalue()


def _plain(d: Decimal | None, places: int | None = None) -> str:
    if d is None:
        return ""
    if places is not None:
        d = d.quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)
        return format(d, "f")
    s = format(d.normalize(), "f")
    return "0" if s == "-0" else s
