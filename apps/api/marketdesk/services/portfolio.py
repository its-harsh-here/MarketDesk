"""Persistent ledger with one account per currency (INR, USD). Every write replays every account before committing.

An FX conversion is one stored transaction with two legs: amount + fees leave the source account and the received
amount arrives in the destination account. Amounts are never converted or relabeled in place.
"""

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
    CURRENCIES,
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
    extra: tuple = (),
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
        *(x if isinstance(x, str) else _norm(x) for x in extra),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def fx_extra(t) -> tuple:
    """Fingerprint parts that only FX conversions have (other rows keep their pre-M08 fingerprints)."""
    if t.type != "FX":
        return ()
    return (t.counter_currency or "", t.counter_amount, t.fx_rate, (t.fx_source or "").strip())


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
        fx_extra(t),
    )


def entry_label(t: LedgerTransaction | None, *, type_: str, effective_date: date, symbol: str | None, ref: str) -> str:
    where = f"transaction #{t.id}" if t is not None and t.id else ref.replace("csv:", "CSV row ")
    sym = f" {symbol}" if symbol else ""
    return f"{type_}{sym} on {effective_date.isoformat()} ({where})"


def to_entry(t: LedgerTransaction) -> LedgerEntry:
    """The entry in the transaction's own account (for FX: the paying leg)."""
    sym = t.instrument.symbol if t.instrument else None
    ref = f"txn:{t.id}"
    label = entry_label(t, type_=t.type, effective_date=t.effective_date, symbol=sym, ref=ref)
    if t.type == "FX":
        return LedgerEntry(
            ref=ref,
            type=TxnType.FX_OUT,
            effective_date=t.effective_date,
            seq=t.id or 10**9,
            amount=t.amount,
            fees=t.fees or Decimal(0),
            label=f"FX conversion {t.currency}→{t.counter_currency} on {t.effective_date.isoformat()} "
            f"({label.rsplit('(', 1)[-1]}",
        )
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
        label=label,
    )


def account_entries(txns: list[LedgerTransaction]) -> dict[str, list[LedgerEntry]]:
    """Entries per currency account; an FX conversion contributes one leg to each side."""
    out: dict[str, list[LedgerEntry]] = {c: [] for c in CURRENCIES}
    for t in txns:
        e = to_entry(t)
        out.setdefault(t.currency or "INR", []).append(e)
        if t.type == "FX" and t.counter_currency:
            out.setdefault(t.counter_currency, []).append(
                replace(e, type=TxnType.FX_IN, amount=t.counter_amount, fees=Decimal(0))
            )
    return out


def replay_accounts(entries: dict[str, list[LedgerEntry]]) -> dict[str, LedgerState]:
    return {ccy: replay(items, ccy) for ccy, items in entries.items()}


def all_transactions(db: Session) -> list[LedgerTransaction]:
    return list(db.scalars(select(LedgerTransaction).order_by(LedgerTransaction.effective_date, LedgerTransaction.id)))


def current_states(db: Session) -> tuple[dict[str, LedgerState], list[LedgerTransaction]]:
    txns = all_transactions(db)
    return replay_accounts(account_entries(txns)), txns


def current_state(db: Session, currency: str = "INR") -> tuple[LedgerState, list[LedgerTransaction]]:
    states, txns = current_states(db)
    return states[currency], txns


def cash_effect(t: LedgerTransaction) -> Decimal:
    """Cash change in the transaction's own account (its `currency`)."""
    if t.type == "DEPOSIT" or t.type == "DIVIDEND":
        return t.amount or Decimal(0)
    if t.type == "WITHDRAWAL":
        return -(t.amount or Decimal(0))
    if t.type == "FX":
        return -((t.amount or Decimal(0)) + (t.fees or Decimal(0)))
    if t.type == "BUY":
        return -(money(t.quantity * t.price) + t.fees)
    if t.type == "SELL":
        return money(t.quantity * t.price) - t.fees
    return Decimal(0)


def txn_dict(t: LedgerTransaction, states: dict[str, LedgerState] | LedgerState | None = None) -> dict:
    state = states.get(t.currency) if isinstance(states, dict) else states
    step = state.steps.get(f"txn:{t.id}") if state else None
    effective_rate = None  # INR per 1 USD actually obtained (before fees), the market convention for USD/INR
    if t.type == "FX" and t.amount and t.counter_amount:
        effective_rate = t.amount / t.counter_amount if t.currency == "INR" else t.counter_amount / t.amount
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
        "counter_currency": t.counter_currency,
        "counter_amount": t.counter_amount,
        "fx_rate": t.fx_rate,
        "effective_rate": effective_rate,
        "fx_source": t.fx_source,
        "fx_time": t.fx_time,
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


def ensure_portfolio_instrument(inst: Instrument, account: str | None = None) -> None:
    if (inst.kind or "").upper() in ("INDEX", "CURRENCY"):
        raise AppError(422, "not_holdable", f"{inst.symbol} is an {inst.kind.lower()} and cannot be held.")
    if inst.currency not in CURRENCIES:
        raise AppError(
            422,
            "currency_unsupported",
            f"{inst.symbol} trades in {inst.currency or 'an unverified currency'}. Portfolio accounts exist for "
            f"{' and '.join(CURRENCIES)} only, and amounts are never converted by relabeling; you can still research "
            "this instrument.",
        )
    if account is not None and inst.currency != account:
        raise AppError(
            422,
            "currency_mismatch",
            f"{inst.symbol} trades in {inst.currency}. Record it in the {inst.currency} account, not the {account} "
            f"account; to fund it, record an FX conversion into {inst.currency}.",
            {"fields": [{"field": "currency", "message": f"Use the {inst.currency} account."}]},
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
    counter_currency: str | None = None
    counter_amount: Decimal | None = None
    fx_rate: Decimal | None = None
    fx_source: str | None = None
    fx_time: object = None


def _field_error(field: str, message: str) -> AppError:
    return AppError(422, "validation_error", message, {"fields": [{"field": field, "message": message}]})


def _prepare_fx(payload: dict, notes: str | None) -> TxnData:
    src, dst = payload.get("currency") or "INR", payload.get("counter_currency")
    if dst not in CURRENCIES or dst == src:
        raise _field_error("counter_currency", f"Choose the account to convert into (different from {src}).")
    amount, received, rate = payload.get("amount"), payload.get("counter_amount"), payload.get("fx_rate")
    if amount is None or amount <= 0:
        raise _field_error("amount", f"Enter the {src} amount converted.")
    if received is None or received <= 0:
        raise _field_error("counter_amount", f"Enter the {dst} amount received.")
    source = (payload.get("fx_source") or "").strip()
    if not source:
        raise _field_error("fx_source", "Name the source of the rate (for example the bank or broker).")
    if rate is not None:
        if rate <= 0:
            raise _field_error("fx_rate", "The quoted rate must be greater than zero.")
        implied = amount / rate if src == "INR" else amount * rate
        if abs(implied - received) > max(Decimal("0.01"), received * Decimal("0.02")):
            raise _field_error(
                "fx_rate",
                f"The quoted rate {rate} INR per USD implies {dst} {money(implied)} for {src} {amount}, but {dst} "
                f"{received} was received. Check the rate or the amounts (fees belong in the fees field).",
            )
    for name in ("quantity", "price", "split_from", "split_to"):
        if payload.get(name) is not None:
            raise _field_error(name, "FX conversions take amounts, not quantity or price.")
    return TxnData(
        type="FX",
        effective_date=payload["effective_date"],
        instrument=None,
        quantity=None,
        price=None,
        fees=payload.get("fees") or Decimal(0),
        amount=amount,
        split_from=None,
        split_to=None,
        currency=src,
        notes=notes,
        counter_currency=dst,
        counter_amount=received,
        fx_rate=rate,
        fx_source=source[:80],
        fx_time=payload.get("fx_time"),
    )


async def prepare(db: Session, market: MarketDataService, payload: dict) -> TxnData:
    t = payload["type"]
    account = payload.get("currency") or "INR"
    if account not in CURRENCIES:
        raise _field_error("currency", f"Accounts exist for {' and '.join(CURRENCIES)} only.")
    notes = payload.get("notes")
    notes = notes.strip() or None if isinstance(notes, str) else None
    if t == "FX":
        if payload.get("symbol"):
            raise _field_error("symbol", "FX conversions do not reference an instrument.")
        return _prepare_fx(payload, notes)
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
        ensure_portfolio_instrument(inst, account)
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
        currency=account,
        notes=notes,
    )


def _apply(t: LedgerTransaction, d: TxnData) -> None:
    t.type = d.type
    t.effective_date = d.effective_date
    t.instrument_id = d.instrument.id if d.instrument else None
    t.instrument = d.instrument
    t.quantity, t.price, t.fees, t.amount = d.quantity, d.price, d.fees, d.amount
    t.split_from, t.split_to, t.currency, t.notes = d.split_from, d.split_to, d.currency, d.notes
    t.counter_currency, t.counter_amount, t.fx_rate = d.counter_currency, d.counter_amount, d.fx_rate
    t.fx_source, t.fx_time = d.fx_source, d.fx_time
    t.fingerprint = txn_fingerprint(t)


def _validate(txns: list[LedgerTransaction], candidate: LedgerTransaction, replace_id: int | None) -> None:
    others = [t for t in txns if t.id != replace_id]
    entries = account_entries(others)
    draft = account_entries([candidate])
    for ccy, items in draft.items():
        for e in items:
            if replace_id is None:
                e = replace(
                    e,
                    ref="new",
                    seq=10**9,
                    label=f"{candidate.type} on {candidate.effective_date.isoformat()} (this entry)",
                )
            entries.setdefault(ccy, []).append(e)
    try:
        replay_accounts(entries)
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
            replay_accounts(account_entries([x for x in txns if x.id != tid]))
        except LedgerError as err:
            raise AppError(
                422,
                "ledger_rejected",
                f"Deleting transaction #{tid} would break the ledger: {err.message}",
                {"ledger_error": err.to_dict()},
            ) from err
        db.delete(t)
        db.commit()


def list_transactions(
    db: Session, limit: int, offset: int, symbol: str | None, type_: str | None, currency: str | None = None
) -> dict:
    states, txns = current_states(db)
    filtered = [
        t
        for t in reversed(txns)
        if (symbol is None or (t.instrument and t.instrument.symbol == symbol))
        and (type_ is None or t.type == type_)
        and (currency is None or t.currency == currency or t.counter_currency == currency)
    ]
    page = filtered[offset : offset + limit]
    return {"items": [txn_dict(t, states) for t in page], "total": len(filtered), "limit": limit, "offset": offset}


async def portfolio_summary(db: Session, market: MarketDataService, currency: str = "INR") -> dict:
    if currency not in CURRENCIES:
        raise _field_error("currency", f"Accounts exist for {' and '.join(CURRENCIES)} only.")
    states, all_txns = current_states(db)
    state = states[currency]
    txns = [t for t in all_txns if t.currency == currency or t.counter_currency == currency]
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
        "currency": currency,
        "has_transactions": bool(txns),
        "fx_in": state.fx_in,
        "fx_out": state.fx_out,
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


OVERVIEW_NOTE = (
    "Each account is valued in its own currency. The base-currency figures convert today's balances at the current "
    "valuation rate shown, for display only: transactions keep their original currency and amounts, and no "
    "historical rate is applied, so no consolidated profit or return is shown."
)


async def portfolio_overview(db: Session, market: MarketDataService, base: str = "INR") -> dict:
    from marketdesk.services.fx import valuation_rate

    accounts, reasons, stale = [], [], []
    for ccy in CURRENCIES:
        summ = await portfolio_summary(db, market, ccy)
        if not summ["has_transactions"]:
            continue
        rate = await valuation_rate(market, ccy, base)
        r = rate.get("rate")
        if not summ["complete"]:
            reasons.append(
                f"{ccy} account: no usable price for {', '.join(summ['missing_marks'])}, so its value is incomplete."
            )
        if r is None:
            reasons.append(
                f"No usable {rate['pair']} valuation rate ({rate.get('message') or rate.get('status')}); the {ccy} "
                f"account is not converted."
            )
        elif rate.get("status") == "stale":
            stale.append(rate["pair"])
        accounts.append(
            {
                "currency": ccy,
                "cash": summ["cash"],
                "holdings_value": summ["holdings_value"],
                "total_equity": summ["total_equity"],
                "partial_equity": summ["partial_equity"],
                "complete": summ["complete"],
                "stale_marks": summ["stale_marks"],
                "value_in_base": money(summ["total_equity"] * r) if r is not None and summ["complete"] else None,
                "partial_in_base": money(summ["partial_equity"] * r) if r is not None else None,
                "rate": rate,
            }
        )
    complete = bool(accounts) and not reasons
    return {
        "base_currency": base,
        "accounts": accounts,
        "complete": complete,
        "total_in_base": sum((a["value_in_base"] for a in accounts), Decimal(0)) if complete else None,
        "partial_in_base": sum((a["partial_in_base"] or Decimal(0) for a in accounts), Decimal(0)),
        "incomplete_reasons": reasons,
        "stale_rates": stale,
        "note": OVERVIEW_NOTE,
    }
