"""JSON round-tripping for provider value types (used by the persisted cache)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from marketdesk.providers.base import (
    AnnualPeriod,
    AnnualStatements,
    CorporateAction,
    DailyBar,
    Fundamentals,
    InstrumentRef,
    NewsItem,
    PriceHistory,
    QuoteSnapshot,
)


def _d(v: Decimal | None) -> str | None:
    return None if v is None else format(v, "f")


def _pd(v: Any) -> Decimal | None:
    return None if v is None else Decimal(v)


def _date(v: str | None) -> date | None:
    return None if v is None else date.fromisoformat(v)


def ref_to(r: InstrumentRef) -> dict:
    return r.to_dict()


def ref_from(d: dict) -> InstrumentRef:
    return InstrumentRef(**d)


def bar_to(b: DailyBar) -> list:
    return [b.session_date.isoformat(), _d(b.open), _d(b.high), _d(b.low), _d(b.close), b.volume]


def bar_from(v: list) -> DailyBar:
    return DailyBar(date.fromisoformat(v[0]), _pd(v[1]), _pd(v[2]), _pd(v[3]), Decimal(v[4]), v[5])


def quote_to(q: QuoteSnapshot) -> dict:
    return {
        "instrument": ref_to(q.instrument),
        "last_price": _d(q.last_price),
        "previous_close": _d(q.previous_close),
        "market_time": q.market_time.isoformat(),
        "session_date": q.session_date.isoformat() if q.session_date else None,
        "day_high": _d(q.day_high),
        "day_low": _d(q.day_low),
        "volume": q.volume,
        "volume_note": q.volume_note,
        "recent_bars": [bar_to(b) for b in q.recent_bars],
    }


def quote_from(d: dict) -> QuoteSnapshot:
    return QuoteSnapshot(
        instrument=ref_from(d["instrument"]),
        last_price=Decimal(d["last_price"]),
        previous_close=_pd(d["previous_close"]),
        market_time=datetime.fromisoformat(d["market_time"]),
        session_date=_date(d["session_date"]),
        day_high=_pd(d["day_high"]),
        day_low=_pd(d["day_low"]),
        volume=d["volume"],
        volume_note=d["volume_note"],
        recent_bars=[bar_from(b) for b in d["recent_bars"]],
    )


def history_to(h: PriceHistory) -> dict:
    return {
        "instrument": ref_to(h.instrument),
        "range": h.range,
        "bars": [bar_to(b) for b in h.bars],
        "adjustment": h.adjustment,
    }


def history_from(d: dict) -> PriceHistory:
    return PriceHistory(ref_from(d["instrument"]), d["range"], [bar_from(b) for b in d["bars"]], d["adjustment"])


_FUND_DEC = (
    "market_cap",
    "pe_ratio",
    "dividend_yield_percent",
    "fifty_two_week_high",
    "fifty_two_week_low",
    "price_to_book",
)


def fundamentals_to(f: Fundamentals) -> dict:
    out = {k: _d(getattr(f, k)) for k in _FUND_DEC}
    out.update(
        instrument=ref_to(f.instrument),
        sector=f.sector,
        industry=f.industry,
        last_fiscal_year_end=f.last_fiscal_year_end.isoformat() if f.last_fiscal_year_end else None,
        most_recent_quarter=f.most_recent_quarter.isoformat() if f.most_recent_quarter else None,
        notes=list(f.notes),
        summary=f.summary,
    )
    return out


def fundamentals_from(d: dict) -> Fundamentals:
    return Fundamentals(
        instrument=ref_from(d["instrument"]),
        **{k: _pd(d[k]) for k in _FUND_DEC},
        sector=d["sector"],
        industry=d["industry"],
        last_fiscal_year_end=_date(d["last_fiscal_year_end"]),
        most_recent_quarter=_date(d["most_recent_quarter"]),
        notes=list(d["notes"]),
        summary=d.get("summary"),  # absent in entries cached before T1
    )


def statements_to(st: AnnualStatements) -> dict:
    return {
        "instrument": ref_to(st.instrument),
        "periods": [
            [
                p.period_end.isoformat(),
                _d(p.revenue),
                _d(p.net_income),
                _d(p.total_debt),
                _d(p.total_equity),
                _d(p.operating_cash_flow),
                _d(p.capex),
                _d(p.cash),
            ]
            for p in st.periods
        ],
        "source": st.source,
        "notes": list(st.notes),
    }


def statements_from(d: dict) -> AnnualStatements:
    def period(p: list) -> AnnualPeriod:
        extra = [_pd(x) for x in p[5:8]] + [None] * (8 - max(len(p), 5))  # entries cached before M11 have 5 fields
        return AnnualPeriod(date.fromisoformat(p[0]), _pd(p[1]), _pd(p[2]), _pd(p[3]), _pd(p[4]), *extra[:3])

    return AnnualStatements(
        instrument=ref_from(d["instrument"]),
        periods=[period(p) for p in d["periods"]],
        source=d["source"],
        notes=list(d["notes"]),
    )


def actions_to(actions: list[CorporateAction]) -> list:
    return [[a.action_date.isoformat(), a.kind, _d(a.value), a.description] for a in actions]


def actions_from(v: list) -> list[CorporateAction]:
    return [CorporateAction(date.fromisoformat(a[0]), a[1], Decimal(a[2]), a[3]) for a in v]


def news_to(items: list[NewsItem]) -> list:
    return [
        [n.title, n.publisher, n.url, n.published_at.isoformat() if n.published_at else None, n.kind] for n in items
    ]


def news_from(v: list) -> list[NewsItem]:
    return [NewsItem(a[0], a[1], a[2], datetime.fromisoformat(a[3]) if a[3] else None, a[4]) for a in v]


def search_to(refs: list[InstrumentRef]) -> list:
    return [ref_to(r) for r in refs]


def search_from(v: list) -> list[InstrumentRef]:
    return [ref_from(r) for r in v]


CODECS = {
    "quote": (quote_to, quote_from),
    "history": (history_to, history_from),
    "fundamentals": (fundamentals_to, fundamentals_from),
    "statements": (statements_to, statements_from),
    "actions": (actions_to, actions_from),
    "search": (search_to, search_from),
    "news": (news_to, news_from),
}
