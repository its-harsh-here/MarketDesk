"""Pure ledger arithmetic (average-cost convention, long-only), one replay per currency account.

Rules
- Each currency (INR, USD) is a separate account with its own cash; amounts are never converted
  or relabeled inside the ledger. Money uses Decimal with 2 decimal places (paise/cents): each
  cash movement is rounded half-up to 2 places when it settles. Cost basis and average unit cost keep full precision
  and are only rounded for presentation.
- BUY:   cash -= round2(qty * price) + fees; basis += round2(qty * price) + fees.
- SELL:  released basis = basis * qty_sold / qty_held (== qty * average cost);
         proceeds = round2(qty * price); cash += proceeds - fees;
         realized P&L = proceeds - fees - released basis.
- SPLIT: qty *= split_to / split_from; basis unchanged (average cost falls). Splits are only
         applied through explicit, confirmed SPLIT transactions, never by adjusting quantities.
- DIVIDEND: cash += amount; tracked separately from realized trading P&L.
- FX conversion (stored as one FX transaction): in the source account FX_OUT takes amount + fees;
  in the destination account FX_IN adds the amount received. Both are transfers, not deposits.
- Replay order: effective date, then intra-day priority (deposit/FX in, split, dividend, trades,
  withdrawal/FX out), then entry sequence. Any intermediate negative cash or oversell is rejected.
- Average cost is an analytical convention, not a tax computation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

PAISE = Decimal("0.01")
ZERO = Decimal("0")
MAX_QTY_PLACES = 6
MAX_PRICE_PLACES = 4
MAX_MONEY_PLACES = 2


class TxnType(StrEnum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    SPLIT = "SPLIT"
    FX_IN = "FX_IN"  # internal: the receiving side of an FX conversion
    FX_OUT = "FX_OUT"  # internal: the paying side of an FX conversion


CURRENCIES = ("INR", "USD")
INTRADAY_PRIORITY = {
    TxnType.DEPOSIT: 0,
    TxnType.FX_IN: 0,
    TxnType.SPLIT: 1,
    TxnType.DIVIDEND: 2,
    TxnType.BUY: 3,
    TxnType.SELL: 3,
    TxnType.WITHDRAWAL: 4,
    TxnType.FX_OUT: 4,
}


def money(value: Decimal) -> Decimal:
    return value.quantize(PAISE, rounding=ROUND_HALF_UP)


def places(value: Decimal) -> int:
    exp = value.normalize().as_tuple().exponent
    return max(0, -exp) if isinstance(exp, int) else 0


class LedgerError(Exception):
    def __init__(self, ref: str, message: str, field: str | None = None, effective_date: date | None = None):
        super().__init__(message)
        self.ref = ref
        self.message = message
        self.field = field
        self.effective_date = effective_date

    def to_dict(self) -> dict:
        return {
            "ref": self.ref,
            "message": self.message,
            "field": self.field,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
        }


@dataclass(frozen=True)
class LedgerEntry:
    ref: str  # e.g. "txn:12" or "csv:5" — used to explain the offending row
    type: TxnType
    effective_date: date
    seq: int
    symbol: str | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    fees: Decimal = ZERO
    amount: Decimal | None = None
    split_from: Decimal | None = None
    split_to: Decimal | None = None
    label: str = ""  # human description of the row for error messages


@dataclass
class Position:
    symbol: str
    quantity: Decimal = ZERO
    cost_basis: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    dividends: Decimal = ZERO
    fees: Decimal = ZERO
    first_date: date | None = None

    @property
    def average_cost(self) -> Decimal | None:
        if self.quantity == 0:
            return None
        return self.cost_basis / self.quantity


@dataclass
class StepResult:
    ref: str
    cash_after: Decimal
    realized_pnl: Decimal | None = None
    quantity_after: Decimal | None = None


@dataclass
class LedgerState:
    cash: Decimal = ZERO
    positions: dict[str, Position] = field(default_factory=dict)
    deposits: Decimal = ZERO
    withdrawals: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    dividends: Decimal = ZERO
    fees: Decimal = ZERO
    fx_in: Decimal = ZERO  # converted into this account
    fx_out: Decimal = ZERO  # converted out of this account, excluding conversion fees
    currency: str = "INR"
    steps: dict[str, StepResult] = field(default_factory=dict)

    @property
    def open_positions(self) -> list[Position]:
        return [p for p in self.positions.values() if p.quantity > 0]

    @property
    def net_contributions(self) -> Decimal:
        return self.deposits - self.withdrawals


def _describe(e: LedgerEntry) -> str:
    return e.label or f"{e.type.value} on {e.effective_date.isoformat()}"


def validate_entry(e: LedgerEntry) -> None:
    """Field-level validation independent of ledger state."""

    def need(cond: bool, field_name: str, message: str) -> None:
        if not cond:
            raise LedgerError(e.ref, message, field_name, e.effective_date)

    def check_places(value: Decimal | None, field_name: str, maxp: int) -> None:
        if value is not None:
            need(value.is_finite(), field_name, f"{field_name} must be a finite number.")
            need(places(value) <= maxp, field_name, f"{field_name} allows at most {maxp} decimal places.")

    need(e.fees is not None and e.fees >= 0, "fees", "Fees cannot be negative.")
    check_places(e.fees, "fees", MAX_MONEY_PLACES)
    t = e.type
    if t in (TxnType.DEPOSIT, TxnType.WITHDRAWAL, TxnType.FX_IN, TxnType.FX_OUT):
        need(e.symbol is None, "symbol", f"{t.value} must not reference an instrument.")
        need(e.amount is not None and e.amount > 0, "amount", "Amount must be greater than zero.")
        check_places(e.amount, "amount", MAX_MONEY_PLACES)
        need(e.quantity is None and e.price is None, "quantity", f"{t.value} does not take quantity or price.")
        if t != TxnType.FX_OUT:  # conversion fees are charged on the paying side
            need(e.fees == 0, "fees", f"{t.value} does not take fees; record the net amount.")
    elif t in (TxnType.BUY, TxnType.SELL):
        need(bool(e.symbol), "symbol", "An instrument is required.")
        need(e.quantity is not None and e.quantity > 0, "quantity", "Quantity must be greater than zero.")
        need(e.price is not None and e.price > 0, "price", "Price must be greater than zero.")
        check_places(e.quantity, "quantity", MAX_QTY_PLACES)
        check_places(e.price, "price", MAX_PRICE_PLACES)
        need(e.amount is None, "amount", "Trades derive their amount from quantity × price.")
    elif t == TxnType.DIVIDEND:
        need(bool(e.symbol), "symbol", "An instrument is required.")
        need(e.amount is not None and e.amount > 0, "amount", "Dividend amount must be greater than zero.")
        check_places(e.amount, "amount", MAX_MONEY_PLACES)
        need(e.fees == 0, "fees", "Record the dividend net of deductions; fees are not used.")
    elif t == TxnType.SPLIT:
        need(bool(e.symbol), "symbol", "An instrument is required.")
        need(e.split_from is not None and e.split_from > 0, "split_from", "Split 'from' must be greater than zero.")
        need(e.split_to is not None and e.split_to > 0, "split_to", "Split 'to' must be greater than zero.")
        need(e.split_from != e.split_to, "split_to", "A split ratio of 1:1 has no effect.")
        need(e.fees == 0, "fees", "Splits do not take fees.")
    else:  # pragma: no cover
        raise LedgerError(e.ref, f"Unsupported transaction type {t}.", "type", e.effective_date)


def sort_entries(entries: list[LedgerEntry]) -> list[LedgerEntry]:
    return sorted(entries, key=lambda e: (e.effective_date, INTRADAY_PRIORITY[e.type], e.seq))


def replay(entries: list[LedgerEntry], currency: str = "INR") -> LedgerState:
    """Replay one currency account's ledger, raising LedgerError at the first invalid row."""
    state = LedgerState(currency=currency)
    for e in sort_entries(entries):
        validate_entry(e)
        realized: Decimal | None = None
        pos: Position | None = None
        if e.symbol:
            pos = state.positions.get(e.symbol)
            if pos is None:
                pos = Position(symbol=e.symbol)
                state.positions[e.symbol] = pos

        if e.type == TxnType.DEPOSIT:
            assert e.amount is not None
            state.cash += e.amount
            state.deposits += e.amount
        elif e.type == TxnType.WITHDRAWAL:
            assert e.amount is not None
            state.cash -= e.amount
            state.withdrawals += e.amount
        elif e.type == TxnType.FX_IN:
            assert e.amount is not None
            state.cash += e.amount
            state.fx_in += e.amount
        elif e.type == TxnType.FX_OUT:
            assert e.amount is not None
            state.cash -= e.amount + e.fees
            state.fx_out += e.amount
            state.fees += e.fees
        elif e.type == TxnType.BUY:
            assert pos is not None and e.quantity is not None and e.price is not None
            cost = money(e.quantity * e.price) + e.fees
            state.cash -= cost
            pos.quantity += e.quantity
            pos.cost_basis += cost
            pos.fees += e.fees
            state.fees += e.fees
            pos.first_date = pos.first_date or e.effective_date
        elif e.type == TxnType.SELL:
            assert pos is not None and e.quantity is not None and e.price is not None
            if e.quantity > pos.quantity:
                raise LedgerError(
                    e.ref,
                    f"{_describe(e)} sells {e.quantity} {e.symbol} but only {pos.quantity} are held at that point.",
                    "quantity",
                    e.effective_date,
                )
            if e.quantity == pos.quantity:
                released = pos.cost_basis
            else:
                released = pos.cost_basis * e.quantity / pos.quantity
            proceeds = money(e.quantity * e.price)
            realized = proceeds - e.fees - released
            state.cash += proceeds - e.fees
            pos.quantity -= e.quantity
            pos.cost_basis -= released
            if pos.quantity == 0:
                pos.cost_basis = ZERO
            pos.realized_pnl += realized
            pos.fees += e.fees
            state.realized_pnl += realized
            state.fees += e.fees
        elif e.type == TxnType.DIVIDEND:
            assert pos is not None and e.amount is not None
            if pos.first_date is None or pos.first_date > e.effective_date:
                raise LedgerError(
                    e.ref,
                    f"{_describe(e)} records a dividend for {e.symbol}, which was never held on or before that date.",
                    "symbol",
                    e.effective_date,
                )
            state.cash += e.amount
            pos.dividends += e.amount
            state.dividends += e.amount
        elif e.type == TxnType.SPLIT:
            assert pos is not None and e.split_from is not None and e.split_to is not None
            if pos.quantity <= 0:
                raise LedgerError(
                    e.ref,
                    f"{_describe(e)} splits {e.symbol}, but no shares are held at that point.",
                    "symbol",
                    e.effective_date,
                )
            pos.quantity = pos.quantity * e.split_to / e.split_from
            # basis unchanged; average cost falls proportionally

        if state.cash < 0:
            raise LedgerError(
                e.ref,
                f"{_describe(e)} would make {currency} cash negative ({currency} {money(state.cash)}). "
                f"Record a deposit or conversion into the {currency} account on or before this date first.",
                "amount" if e.type in (TxnType.WITHDRAWAL, TxnType.FX_OUT) else "quantity",
                e.effective_date,
            )
        state.steps[e.ref] = StepResult(
            ref=e.ref,
            cash_after=state.cash,
            realized_pnl=realized,
            quantity_after=pos.quantity if pos is not None else None,
        )
    return state


# --------------------------------------------------------------------------- valuation
@dataclass(frozen=True)
class Mark:
    price: Decimal
    status: str  # sample | available | cached | stale
    market_time: str | None = None


@dataclass
class HoldingValuation:
    symbol: str
    quantity: Decimal
    average_cost: Decimal | None
    cost_basis: Decimal
    realized_pnl: Decimal
    dividends: Decimal
    last_price: Decimal | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    unrealized_pct: Decimal | None
    mark_status: str  # status of the mark, or "missing"
    mark_time: str | None
    weight_pct: Decimal | None = None


@dataclass
class PortfolioValuation:
    cash: Decimal
    holdings: list[HoldingValuation]
    holdings_value: Decimal  # sum over holdings that have a usable mark
    total_equity: Decimal | None  # None when valuation is incomplete
    partial_equity: Decimal  # cash + valued holdings (explicitly partial when incomplete)
    unrealized_pnl: Decimal | None
    realized_pnl: Decimal
    dividends: Decimal
    fees: Decimal
    total_profit_before_dividends: Decimal | None
    deposits: Decimal
    withdrawals: Decimal
    net_contributions: Decimal
    complete: bool
    missing_marks: list[str]
    stale_marks: list[str]
    cash_weight_pct: Decimal | None


def value_portfolio(state: LedgerState, marks: dict[str, Mark | None]) -> PortfolioValuation:
    holdings: list[HoldingValuation] = []
    missing: list[str] = []
    stale: list[str] = []
    valued_total = ZERO
    unrealized_total = ZERO
    for pos in sorted(state.open_positions, key=lambda p: p.symbol):
        mark = marks.get(pos.symbol)
        if mark is None:
            missing.append(pos.symbol)
            holdings.append(
                HoldingValuation(
                    pos.symbol,
                    pos.quantity,
                    pos.average_cost,
                    pos.cost_basis,
                    pos.realized_pnl,
                    pos.dividends,
                    None,
                    None,
                    None,
                    None,
                    "missing",
                    None,
                )
            )
            continue
        if mark.status == "stale":
            stale.append(pos.symbol)
        mv = pos.quantity * mark.price
        upnl = mv - pos.cost_basis
        upct = (upnl / pos.cost_basis * 100) if pos.cost_basis else None
        valued_total += mv
        unrealized_total += upnl
        holdings.append(
            HoldingValuation(
                pos.symbol,
                pos.quantity,
                pos.average_cost,
                pos.cost_basis,
                pos.realized_pnl,
                pos.dividends,
                mark.price,
                mv,
                upnl,
                upct,
                mark.status,
                mark.market_time,
            )
        )
    complete = not missing
    partial_equity = state.cash + valued_total
    denominator = partial_equity if complete and partial_equity > 0 else None
    if denominator:
        for h in holdings:
            if h.market_value is not None:
                h.weight_pct = h.market_value / denominator * 100
    return PortfolioValuation(
        cash=state.cash,
        holdings=holdings,
        holdings_value=valued_total,
        total_equity=partial_equity if complete else None,
        partial_equity=partial_equity,
        unrealized_pnl=unrealized_total if complete else None,
        realized_pnl=state.realized_pnl,
        dividends=state.dividends,
        fees=state.fees,
        total_profit_before_dividends=(state.realized_pnl + unrealized_total) if complete else None,
        deposits=state.deposits,
        withdrawals=state.withdrawals,
        net_contributions=state.net_contributions,
        complete=complete,
        missing_marks=missing,
        stale_marks=stale,
        cash_weight_pct=(state.cash / denominator * 100) if denominator else None,
    )
