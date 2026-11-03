"""Instrument registry: validates symbols with the active provider and stores metadata once."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.models import Instrument
from marketdesk.providers.base import InstrumentRef, ProviderError
from marketdesk.services.market import MarketDataService


def find_instrument(db: Session, provider: str, symbol: str) -> Instrument | None:
    return db.scalar(select(Instrument).where(Instrument.provider == provider, Instrument.symbol == symbol))


def upsert_instrument(db: Session, provider: str, ref: InstrumentRef) -> Instrument:
    inst = find_instrument(db, provider, ref.symbol)
    if inst is None:
        inst = Instrument(provider=provider, symbol=ref.symbol)
        db.add(inst)
    for attr in ("name", "exchange", "currency", "timezone", "kind"):
        value = getattr(ref, attr)
        if value:
            setattr(inst, attr, value)
    db.flush()
    return inst


def instrument_dict(inst: Instrument | None, fallback: InstrumentRef | None = None, symbol: str = "") -> dict:
    if inst is not None:
        return {
            "symbol": inst.symbol,
            "name": inst.name,
            "exchange": inst.exchange,
            "currency": inst.currency,
            "timezone": inst.timezone,
            "kind": inst.kind,
        }
    if fallback is not None:
        return fallback.to_dict()
    return {"symbol": symbol, "name": None, "exchange": None, "currency": None, "timezone": None, "kind": None}


def validate_symbol(market: MarketDataService, symbol: str) -> str:
    try:
        return market.validate_symbol(symbol)
    except ProviderError as err:
        raise AppError(422, "unsupported_symbol", err.message) from err


async def resolve_instrument(db: Session, market: MarketDataService, symbol: str) -> Instrument:
    """Return a registered instrument, verifying unknown symbols with the provider first."""
    sym = validate_symbol(market, symbol)
    existing = find_instrument(db, market.source, sym)
    if existing is not None and existing.currency:
        return existing
    quote = await market.quote(sym)
    ref: InstrumentRef | None = quote.value.instrument if quote.value else None
    if ref is None:
        hist = await market.history(sym, "1M")
        ref = hist.value.instrument if hist.value else None
        if ref is None:
            if existing is not None:
                return existing
            reason = quote.meta.message or hist.meta.message or "The provider has no data for this symbol."
            status = 503 if quote.meta.status == "unavailable" else 422
            raise AppError(status, "symbol_unverified", f"Could not verify {sym}: {reason}")
    inst = upsert_instrument(db, market.source, ref)
    db.commit()
    return inst
