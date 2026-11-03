"""Persistent INR ledger. Every write replays the whole ledger before committing."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.models import Instrument, LedgerTransaction
from marketdesk.services.instruments import resolve_instrument
from marketdesk.services.ledger import (
    LedgerEntry,
    LedgerError,
    LedgerState,
    Mark,
    TxnType,
    money,
    replay,
    value_portfolio,
)
from marketdesk.services.market import MarketDataService

# One writer at a time: validation and commit must see the same ledger.
LEDGER_LOCK = threading.Lock()
ACCOUNTING_NOTE = (
    "Average-cost convention for analysis only; not a tax computation. Realized P&L and dividends are "
    "tracked separately. Net contributions (deposits minus withdrawals) are not gains."
)
USABLE_MARK_STATUSES = {"sample", "available", "cached", "stale"}


def _norm(d: Decimal | None) -> str:
    if d is None:
        return ""
    s = format(d.normalize(), "f")
    return "0" if s == "-0" else s


def fingerprint(
    effective_date: date,
    type_: str,
    symbol: str | None,
    quantity,
    price,
    fees,
    amount,
    split_from,
    split_to,
    currency: str,
    notes: str | None,
) -> str:
    parts = [
        effective_date.isoformat(),
        type_,
        symbol or "",
        _norm(quantity),
        _norm(price),
        _norm(fees),
        _norm(amount),
        _norm(split_from),
        _norm(split_to),
        currency,
        " ".join((notes or "").split()),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def txn_fingerprint(t: LedgerTransaction) -> str:
    return fingerprint(
        t.effective_date,
        t.type,
        t.instrument.symbol if t.instrument else None,
        t.quantity,
        t.price,
        t.fees,
        t.amount,
        t.split_from,
        t.split_to,
        t.currency,
        t.notes,
    )


def entry_label(t: LedgerTransaction | None, *, type_: str, effective_date: date, symbol: str | None, ref: str) -> str:
    where = f"transaction #{t.id}" if t is not None and t.id else ref.replace("csv:", "CSV row ")
    sym = f" {symbol}" if symbol else ""
    return f"{type_}{sym} on {effective_date.isoformat()} ({where})"


def to_entry(t: LedgerTransaction) -> LedgerEntry:
    sym = t.instrument.symbol if t.instrument else None
    ref = f"txn:{t.id}"
    return LedgerEntry(
        ref=ref,
        type=TxnType(t.type),
        effective_date=t.effective_date,
        seq=t.id or 10**9,
        symbol=sym,
        quantity=t.quantity,
        price=t.price,
        fees=t.fees or Decimal(0),
        amount=t.amount,
        split_from=t.split_from,
        split_to=t.split_to,
        label=entry_label(t, type_=t.type, effective_date=t.effective_date, symbol=sym, ref=ref),
    )


def all_transactions(db: Session) -> list[LedgerTransaction]:
    return list(db.scalars(select(LedgerTransaction).order_by(LedgerTransaction.effective_date, LedgerTransaction.id)))


def current_state(db: Session) -> tuple[LedgerState, list[LedgerTransaction]]:
    txns = all_transactions(db)
    return replay([to_entry(t) for t in txns]), txns


def cash_effect(t: LedgerTransaction) -> Decimal:
    if t.type == "DEPOSIT" or t.type == "DIVIDEND":
        return t.amount or Decimal(0)
    if t.type == "WITHDRAWAL":
        return -(t.amount or Decimal(0))
    if t.type == "BUY":
        return -(money(t.quantity * t.price) + t.fees)
    if t.type == "SELL":
        return money(t.quantity * t.price) - t.fees
    return Decimal(0)


def txn_dict(t: LedgerTransaction, state: LedgerState | None = None) -> dict:
    step = state.steps.get(f"txn:{t.id}") if state else None
    return {
        "id": t.id,
        "type": t.type,
        "effective_date": t.effective_date,
        "symbol": t.instrument.symbol if t.instrument else None,
        "instrument_name": t.instrument.name if t.instrument else None,
        "quantity": t.quantity,
        "price": t.price,
        "fees": t.fees,
        "amount": t.amount,
        "split_from": t.split_from,
        "split_to": t.split_to,
        "currency": t.currency,
        "notes": t.notes,
        "source": t.source,
        "cash_effect": cash_effect(t),
        "cash_after": step.cash_after if step else None,
        "realized_pnl": step.realized_pnl if step else None,
        "created_at": t.created_at,
        "created_via": t.created_via,
        "updated_at": t.updated_at,
    }


def ledger_rejection(err: LedgerError) -> AppError:
    return AppError(
        422,
        "ledger_rejected",
        err.message,
        {"ledger_error": err.to_dict(), "fields": [{"field": err.field, "message": err.message}]},
    )


def ensure_portfolio_instrument(inst: Instrument) -> None:
    if (inst.kind or "").upper() == "INDEX":
        raise AppError(422, "not_holdable", f"{inst.symbol} is an index and cannot be held in the portfolio.")
    if inst.currency != "INR":
        raise AppError(
            422,
            "currency_unsupported",
            f"{inst.symbol} trades in {inst.currency or 'an unverified currency'}. The v1 portfolio is INR-only and "
            "does not convert currencies; you can still research this instrument.",
        )


@dataclass
class TxnData:
    type: str
    effective_date: date
    instrument: Instrument | None
    quantity: Decimal | None
    price: Decimal | None
    fees: Decimal
    amount: Decimal | None
    split_from: Decimal | None
    split_to: Decimal | None
    currency: str
    notes: str | None


async def prepare(db: Session, market: MarketDataService, payload: dict) -> TxnData:
    t = payload["type"]
    needs_symbol = t in ("BUY", "SELL", "DIVIDEND", "SPLIT")
    inst = None
    if needs_symbol:
        if not payload.get("symbol"):
            raise AppError(
                422,
                "validation_error",
                "An instrument is required.",
                {"fields": [{"field": "symbol", "message": "Choose an instrument."}]},
            )
        inst = await resolve_instrument(db, market, payload["symbol"])
        ensure_portfolio_instrument(inst)
    elif payload.get("symbol"):
        raise AppError(
            422,
            "validation_error",
            f"{t} must not reference an instrument.",
            {"fields": [{"field": "symbol", "message": "Remove the instrument."}]},
        )
    if t == "SPLIT" and not payload.get("split_confirmed"):
        raise AppError(
            422,
            "split_unconfirmed",
            "Confirm the split explicitly. Enter pre-split trades with their original quantities; "
            "the split is applied once by this transaction.",
            {"fields": [{"field": "split_confirmed", "message": "Confirmation required."}]},
        )
    notes = payload.get("notes")
    notes = notes.strip() or None if isinstance(notes, str) else None
    return TxnData(
        type=t,
        effective_date=payload["effective_date"],
        instrument=inst,
        quantity=payload.get("quantity") if t in ("BUY", "SELL") else None,
        price=payload.get("price") if t in ("BUY", "SELL") else None,
        fees=payload.get("fees") or Decimal(0),
        amount=payload.get("amount") if t in ("DEPOSIT", "WITHDRAWAL", "DIVIDEND") else None,
        split_from=payload.get("split_from") if t == "SPLIT" else None,
        split_to=payload.get("split_to") if t == "SPLIT" else None,
        currency="INR",
        notes=notes,
    )


def _apply(t: LedgerTransaction, d: TxnData) -> None:
    t.type = d.type
    t.effective_date = d.effective_date
    t.instrument_id = d.instrument.id if d.instrument else None
    t.instrument = d.instrument
    t.quantity, t.price, t.fees, t.amount = d.quantity, d.price, d.fees, d.amount
    t.split_from, t.split_to, t.currency, t.notes = d.split_from, d.split_to, d.currency, d.notes
    t.fingerprint = txn_fingerprint(t)


def _validate(txns: list[LedgerTransaction], candidate: LedgerTransaction, replace_id: int | None) -> None:
    entries = [to_entry(t) for t in txns if t.id != replace_id]
    entry = to_entry(candidate)
    if replace_id is None:
        entry = replace(
            entry,
            ref="new",
            seq=10**9,
            label=f"{candidate.type} on {candidate.effective_date.isoformat()} (this entry)",
        )
    try:
        replay([*entries, entry])
    except LedgerError as err:
        raise ledger_rejection(err) from err


async def create_transaction(db: Session, market: MarketDataService, payload: dict) -> LedgerTransaction:
    data = await prepare(db, market, payload)
    with LEDGER_LOCK:
        txns = all_transactions(db)
        t = LedgerTransaction(source="manual", created_via="api")
        _apply(t, data)
        _validate(txns, t, None)
        db.add(t)
        db.commit()
        db.refresh(t)
        return t


async def update_transaction(db: Session, market: MarketDataService, tid: int, payload: dict) -> LedgerTransaction:
    data = await prepare(db, market, payload)
    with LEDGER_LOCK:
        t = db.get(LedgerTransaction, tid)
        if t is None:
            raise AppError(404, "not_found", "Transaction not found.")
        txns = all_transactions(db)
        draft = LedgerTransaction(id=t.id)
        _apply(draft, data)
        _validate(txns, draft, t.id)
        if draft in db:
            db.expunge(draft)
        _apply(t, data)  # creation metadata (created_at, created_via, source) stays immutable
        db.commit()
        db.refresh(t)
        return t


def delete_transaction(db: Session, tid: int) -> None:
    with LEDGER_LOCK:
        t = db.get(LedgerTransaction, tid)
        if t is None:
            raise AppError(404, "not_found", "Transaction not found.")
        txns = all_transactions(db)
        try:
            replay([to_entry(x) for x in txns if x.id != tid])
        except LedgerError as err:
            raise AppError(
                422,
                "ledger_rejected",
                f"Deleting transaction #{tid} would break the ledger: {err.message}",
                {"ledger_error": err.to_dict()},
            ) from err
        db.delete(t)
        db.commit()


def list_transactions(db: Session, limit: int, offset: int, symbol: str | None, type_: str | None) -> dict:
    state, txns = current_state(db)
    filtered = [
        t
        for t in reversed(txns)
        if (symbol is None or (t.instrument and t.instrument.symbol == symbol)) and (type_ is None or t.type == type_)
    ]
    page = filtered[offset : offset + limit]
    return {"items": [txn_dict(t, state) for t in page], "total": len(filtered), "limit": limit, "offset": offset}


async def portfolio_summary(db: Session, market: MarketDataService) -> dict:
    state, txns = current_state(db)
    symbols = [p.symbol for p in state.open_positions]
    quotes = await market.quotes(symbols) if symbols else {}
    marks: dict[str, Mark | None] = {}
    messages: dict[str, str | None] = {}
    for sym, r in quotes.items():
        if r.value is not None and r.meta.status in USABLE_MARK_STATUSES:
            marks[sym] = Mark(r.value.last_price, r.meta.status, r.value.market_time.isoformat())
        else:
            marks[sym] = None
        messages[sym] = r.meta.message
    val = value_portfolio(state, marks)
    insts = (
        {i.symbol: i for i in db.scalars(select(Instrument).where(Instrument.symbol.in_(symbols)))} if symbols else {}
    )
    holdings = []
    for h in val.holdings:
        inst = insts.get(h.symbol)
        holdings.append(
            {
                "symbol": h.symbol,
                "name": inst.name if inst else None,
                "exchange": inst.exchange if inst else None,
                "quantity": h.quantity,
                "average_cost": h.average_cost,
                "cost_basis": h.cost_basis,
                "last_price": h.last_price,
                "market_value": h.market_value,
                "unrealized_pnl": h.unrealized_pnl,
                "unrealized_pct": h.unrealized_pct,
                "realized_pnl": h.realized_pnl,
                "dividends": h.dividends,
                "weight_pct": h.weight_pct,
                "mark_status": h.mark_status,
                "mark_time": h.mark_time,
                "mark_message": messages.get(h.symbol) if h.mark_status in ("missing", "stale") else None,
            }
        )
    return {
        "currency": "INR",
        "has_transactions": bool(txns),
        "cash": val.cash,
        "holdings_value": val.holdings_value,
        "total_equity": val.total_equity,
        "partial_equity": val.partial_equity,
        "unrealized_pnl": val.unrealized_pnl,
        "realized_pnl": val.realized_pnl,
        "dividends": val.dividends,
        "fees": val.fees,
        "total_profit_before_dividends": val.total_profit_before_dividends,
        "deposits": val.deposits,
        "withdrawals": val.withdrawals,
        "net_contributions": val.net_contributions,
        "complete": val.complete,
        "missing_marks": val.missing_marks,
        "stale_marks": val.stale_marks,
        "cash_weight_pct": val.cash_weight_pct,
        "holdings": holdings,
        "accounting_note": ACCOUNTING_NOTE,
        "valuation_source": market.source,
    }


def transaction_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(LedgerTransaction)) or 0
