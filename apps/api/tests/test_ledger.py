from datetime import date
from decimal import Decimal as D

import pytest

from marketdesk.services.ledger import (
    LedgerEntry,
    LedgerError,
    Mark,
    TxnType,
    money,
    replay,
    value_portfolio,
)

SYM = "SX:AURORA"


def e(seq, type_, day, **kw):
    return LedgerEntry(ref=f"txn:{seq}", type=TxnType(type_), effective_date=date(2026, 1, day), seq=seq, **kw)


def acceptance_entries():
    return [
        e(1, "DEPOSIT", 2, amount=D("10000")),
        e(2, "BUY", 3, symbol=SYM, quantity=D("10"), price=D("100"), fees=D("10")),
        e(3, "BUY", 4, symbol=SYM, quantity=D("10"), price=D("120"), fees=D("10")),
        e(4, "SELL", 5, symbol=SYM, quantity=D("5"), price=D("130"), fees=D("5")),
    ]


def test_acceptance_example_from_spec():
    entries = acceptance_entries()
    after_buys = replay(entries[:3])
    pos = after_buys.positions[SYM]
    assert pos.average_cost == D("111")
    assert pos.cost_basis == D("2220")
    assert after_buys.cash == D("7780")

    state = replay(entries)
    pos = state.positions[SYM]
    assert state.steps["txn:4"].realized_pnl == D("90")
    assert pos.quantity == D("15")
    assert pos.cost_basis == D("1665")
    assert state.cash == D("8425")

    val = value_portfolio(state, {SYM: Mark(D("140"), "sample")})
    assert val.holdings_value == D("2100")
    assert val.unrealized_pnl == D("435")
    assert val.total_equity == D("10525")
    assert val.total_profit_before_dividends == D("525")
    assert val.realized_pnl == D("90")
    # net deposits are contributions, not gains
    assert val.net_contributions == D("10000")

    split = replay([*entries, e(5, "SPLIT", 6, symbol=SYM, split_from=D("1"), split_to=D("2"))])
    pos = split.positions[SYM]
    assert pos.quantity == D("30")
    assert pos.average_cost == D("55.5")
    assert pos.cost_basis == D("1665")
    assert split.cash == D("8425")


def test_fees_are_included_in_basis_and_reduce_proceeds():
    state = replay(
        [
            e(1, "DEPOSIT", 2, amount=D("1000")),
            e(2, "BUY", 3, symbol=SYM, quantity=D("3"), price=D("100.10"), fees=D("2.35")),
            e(3, "SELL", 4, symbol=SYM, quantity=D("3"), price=D("101"), fees=D("1.20")),
        ]
    )
    # buy cost 300.30 + 2.35 = 302.65; proceeds 303.00 - 1.20 = 301.80; realized = -0.85
    assert state.realized_pnl == D("-0.85")
    assert state.cash == D("1000") - D("302.65") + D("301.80")
    assert state.fees == D("3.55")
    assert state.positions[SYM].quantity == 0
    assert state.positions[SYM].cost_basis == 0


def test_oversell_is_rejected_with_offending_row():
    with pytest.raises(LedgerError) as exc:
        replay(
            [
                e(1, "DEPOSIT", 2, amount=D("1000")),
                e(2, "BUY", 3, symbol=SYM, quantity=D("2"), price=D("10")),
                e(3, "SELL", 4, symbol=SYM, quantity=D("3"), price=D("10")),
            ]
        )
    assert exc.value.ref == "txn:3"
    assert "only 2" in exc.value.message


def test_negative_cash_is_rejected_at_intermediate_point():
    with pytest.raises(LedgerError) as exc:
        replay(
            [
                e(1, "DEPOSIT", 2, amount=D("100")),
                e(2, "BUY", 3, symbol=SYM, quantity=D("2"), price=D("60")),  # needs 120
                e(3, "DEPOSIT", 9, amount=D("1000")),  # later deposit cannot fix an earlier shortfall
            ]
        )
    assert exc.value.ref == "txn:2"
    assert "negative" in exc.value.message


def test_withdrawal_cannot_overdraw():
    with pytest.raises(LedgerError) as exc:
        replay([e(1, "DEPOSIT", 2, amount=D("50")), e(2, "WITHDRAWAL", 3, amount=D("50.01"))])
    assert exc.value.ref == "txn:2"


def test_historical_edit_replays_whole_ledger():
    entries = acceptance_entries()
    # Editing the first buy to a larger quantity changes everything downstream.
    edited = [entries[0], e(2, "BUY", 3, symbol=SYM, quantity=D("20"), price=D("100"), fees=D("10")), *entries[2:]]
    state = replay(edited)
    pos = state.positions[SYM]
    assert pos.quantity == D("25")
    # Removing the deposit makes the first buy invalid.
    with pytest.raises(LedgerError) as exc:
        replay(entries[1:])
    assert exc.value.ref == "txn:2"


def test_same_day_deposit_is_applied_before_trades():
    state = replay(
        [
            e(2, "BUY", 3, symbol=SYM, quantity=D("1"), price=D("10")),
            e(1, "DEPOSIT", 3, amount=D("10")),
        ]
    )
    assert state.cash == 0


def test_split_requires_position_and_preserves_basis():
    with pytest.raises(LedgerError):
        replay([e(1, "SPLIT", 2, symbol=SYM, split_from=D("1"), split_to=D("2"))])
    state = replay(
        [
            e(1, "DEPOSIT", 2, amount=D("1000")),
            e(2, "BUY", 3, symbol=SYM, quantity=D("3"), price=D("100")),
            e(3, "SPLIT", 4, symbol=SYM, split_from=D("2"), split_to=D("3")),  # 3-for-2
        ]
    )
    pos = state.positions[SYM]
    assert pos.quantity == D("4.5")
    assert pos.cost_basis == D("300")
    assert pos.average_cost == D("300") / D("4.5")


def test_post_split_sell_uses_split_adjusted_average_cost():
    state = replay(
        [
            e(1, "DEPOSIT", 2, amount=D("1000")),
            e(2, "BUY", 3, symbol=SYM, quantity=D("10"), price=D("50")),
            e(3, "SPLIT", 4, symbol=SYM, split_from=D("1"), split_to=D("2")),
            e(4, "SELL", 5, symbol=SYM, quantity=D("5"), price=D("30")),
        ]
    )
    assert state.realized_pnl == D("150") - D("125")


def test_decimal_rounding_settles_cash_to_paise_half_up():
    assert money(D("0.005")) == D("0.01")
    assert money(D("2.344999")) == D("2.34")
    state = replay(
        [
            e(1, "DEPOSIT", 2, amount=D("100")),
            e(2, "BUY", 3, symbol=SYM, quantity=D("0.333333"), price=D("10.0015")),
        ]
    )
    # 0.333333 * 10.0015 = 3.3338299995 -> settles at 3.33
    assert state.cash == D("96.67")
    assert state.positions[SYM].cost_basis == D("3.33")


def test_precision_limits_are_enforced():
    with pytest.raises(LedgerError) as exc:
        replay([e(1, "DEPOSIT", 2, amount=D("10.001"))])
    assert exc.value.field == "amount"
    with pytest.raises(LedgerError):
        replay([e(1, "DEPOSIT", 2, amount=D("100")), e(2, "BUY", 3, symbol=SYM, quantity=D("1"), price=D("1.00001"))])


def test_dividend_requires_prior_holding_and_is_separate_from_realized():
    with pytest.raises(LedgerError):
        replay([e(1, "DEPOSIT", 2, amount=D("100")), e(2, "DIVIDEND", 3, symbol=SYM, amount=D("5"))])
    state = replay(
        [
            e(1, "DEPOSIT", 2, amount=D("100")),
            e(2, "BUY", 3, symbol=SYM, quantity=D("1"), price=D("10")),
            e(3, "DIVIDEND", 4, symbol=SYM, amount=D("2.50")),
        ]
    )
    assert state.dividends == D("2.50")
    assert state.realized_pnl == 0
    assert state.cash == D("92.50")


def test_missing_and_stale_marks_make_valuation_incomplete_not_zero():
    state = replay(
        [
            e(1, "DEPOSIT", 2, amount=D("1000")),
            e(2, "BUY", 3, symbol=SYM, quantity=D("1"), price=D("100")),
            e(3, "BUY", 4, symbol="SX:QUILL", quantity=D("1"), price=D("100")),
        ]
    )
    val = value_portfolio(state, {SYM: Mark(D("110"), "stale"), "SX:QUILL": None})
    assert not val.complete
    assert val.total_equity is None
    assert val.unrealized_pnl is None
    assert val.missing_marks == ["SX:QUILL"]
    assert val.stale_marks == [SYM]
    quill = next(h for h in val.holdings if h.symbol == "SX:QUILL")
    assert quill.market_value is None and quill.mark_status == "missing"
    assert val.partial_equity == D("800") + D("110")
