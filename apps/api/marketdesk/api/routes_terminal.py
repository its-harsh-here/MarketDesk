"""Terminal views (terminal roadmap): one security, every domain, each figure with its source and date."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader, settings_dep
from marketdesk.asyncbridge import off_event_loop
from marketdesk.config import Settings
from marketdesk.db import get_db
from marketdesk.services import converter, description, financial_view, news_stream, perf_overview, security_risk
from marketdesk.services import events as ev
from marketdesk.services import movers as mv
from marketdesk.services.instruments import resolve_instrument
from marketdesk.services.market import MarketDataService

router = APIRouter(prefix="/api/terminal", tags=["terminal"], dependencies=[Depends(require_reader)])


@router.get("/description")
@off_event_loop
async def describe(
    request: Request,
    symbol: str = Query(min_length=1, max_length=32),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    """Identity, business summary, key statistics and a coverage list for one listing (T1)."""
    inst = await resolve_instrument(db, market, symbol)
    analyst = request.app.state.analyst
    finra = request.app.state.finra
    return await description.describe(
        db, market, request.app.state.research, settings, inst, analyst.enabled, finra.enabled
    )


@router.get("/financial-analysis")
@off_event_loop
async def financial_analysis(
    request: Request,
    symbol: str = Query(min_length=1, max_length=32),
    period: Literal["annual", "quarterly"] = Query(default="annual"),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    """Per-share, common-size, growth, CAGR, margins, returns and valuation bands with formulas (T2)."""
    inst = await resolve_instrument(db, market, symbol)
    return await financial_view.build(db, market, request.app.state.research, inst, period)


@router.get("/risk")
@off_event_loop
async def risk(
    request: Request,
    symbol: str = Query(min_length=1, max_length=32),
    benchmark: str | None = Query(default=None, max_length=32),
    universe: str = Query(default="watchlists", pattern=r"^(watchlists|holdings|watchlist:\d+|list:\d+)$"),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    """Benchmark sensitivity, volatility, drawdowns, liquidity, position within a universe, peer P/E history and
    short interest (T6)."""
    inst = await resolve_instrument(db, market, symbol)
    bench = None
    if benchmark:
        bench = (await resolve_instrument(db, market, benchmark)).symbol
    kind, _, uid = universe.partition(":")
    spec = {"kind": kind, **({"id": int(uid)} if uid else {})}
    return security_risk.jsonable(
        await security_risk.build(
            db, market, request.app.state.research, request.app.state.finra, settings, inst, bench, spec
        )
    )


@router.get("/events")
@off_event_loop
async def events(
    request: Request,
    symbol: str = Query(min_length=1, max_length=32),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    """Past and upcoming events for one security: results, dividends, splits, reports, proxies, meetings (T4)."""
    inst = await resolve_instrument(db, market, symbol)
    return ev.jsonable(await ev.security_events(db, market, request.app.state.research, inst))


@router.get("/events/universe")
@off_event_loop
async def universe_events(
    request: Request,
    universe: str = Query(default="watchlists", pattern=r"^(watchlists|holdings|watchlist:\d+|list:\d+)$"),
    ahead: int = Query(default=60, ge=7, le=180),
    back: int = Query(default=30, ge=0, le=90),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    """Events across a declared universe within a window (T4)."""
    kind, _, uid = universe.partition(":")
    spec = {"kind": kind, **({"id": int(uid)} if uid else {})}
    return ev.jsonable(await ev.universe_events(db, market, request.app.state.research, spec, ahead, back))


@router.get("/earnings-history")
@off_event_loop
async def earnings_history(
    request: Request,
    symbol: str = Query(min_length=1, max_length=32),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    """Reported revenue, net income and diluted EPS by period with year-on-year change; no estimates (T4)."""
    inst = await resolve_instrument(db, market, symbol)
    return ev.jsonable(await ev.earnings_history(db, market, request.app.state.research, inst))


@router.get("/news")
@off_event_loop
async def news(
    request: Request,
    symbol: str = Query(min_length=1, max_length=32),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    """Filings (plain-language 8-K items) and provider headlines for one security, newest first; links only (T5)."""
    inst = await resolve_instrument(db, market, symbol)
    return await news_stream.stream(db, market, request.app.state.research, inst)


@router.get("/movers")
@off_event_loop
async def movers(
    universe: str = Query(default="watchlists", pattern=r"^(watchlists|holdings|watchlist:\d+|list:\d+)$"),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
):
    """Gainers, losers, most active, unusual volume and breadth across a declared universe (T9)."""
    kind, _, uid = universe.partition(":")
    spec = {"kind": kind, **({"id": int(uid)} if uid else {})}
    return ev.jsonable(await mv.movers(db, market, spec))


@router.get("/performance")
@off_event_loop
async def performance(
    symbol: str = Query(min_length=1, max_length=32),
    db: Session = Depends(get_db),
    market: MarketDataService = Depends(market_dep),
    settings: Settings = Depends(settings_dep),
):
    """Price return over 1W–5Y and YTD against the market benchmark, and the 52-week range."""
    inst = await resolve_instrument(db, market, symbol)
    return ev.jsonable(await perf_overview.overview(market, settings, inst))


@router.get("/convert")
@off_event_loop
async def convert(
    amount: Decimal = Query(default=Decimal(1), gt=0, le=Decimal("1e12")),
    base: str = Query(alias="from", pattern=r"^[A-Z]{3}$"),
    quote: str = Query(alias="to", pattern=r"^[A-Z]{3}$"),
    market: MarketDataService = Depends(market_dep),
):
    """Convert an amount at the provider's latest quoted rate (indicative)."""
    return ev.jsonable(await converter.convert(market, amount, base, quote))
