"""Instrument registry: validates symbols with the active provider and stores metadata once."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from marketdesk.api.errors import AppError
from marketdesk.models import Instrument, InstrumentIdentifier
from marketdesk.providers.base import InstrumentRef, ProviderError
from marketdesk.services.market import MarketDataService


def find_instrument(db: Session, provider: str, symbol: str) -> Instrument | None:
    return db.scalar(select(Instrument).where(Instrument.provider == provider, Instrument.symbol == symbol))


IDENTITY_ATTRS = ("name", "exchange", "currency", "timezone", "kind", "exchange_code", "mic", "country")


def apply_ref(inst: Instrument, ref: InstrumentRef, provider: str) -> bool:
    """Copy provider metadata onto a stored instrument. Returns True if anything changed.

    Quote/chart metadata (it carries the trading currency) verifies the listing identity; search hits do not.
    """
    changed = False
    for attr in IDENTITY_ATTRS:
        value = getattr(ref, attr, None)
        if value and getattr(inst, attr) != value:
            setattr(inst, attr, value)
            changed = True
    if ref.currency and inst.identity_verified_at is None:
        inst.identity_source = f"{provider} quote metadata"
        inst.identity_verified_at = datetime.now(UTC)
        changed = True
    return changed


def ensure_identifier(db: Session, inst: Instrument, scheme: str, value: str, source: str) -> None:
    exists = db.scalar(
        select(InstrumentIdentifier).where(
            InstrumentIdentifier.instrument_id == inst.id, InstrumentIdentifier.scheme == scheme
        )
    )
    if exists is None:
        db.add(
            InstrumentIdentifier(
                instrument_id=inst.id, scheme=scheme, value=value, source=source, verified_at=datetime.now(UTC)
            )
        )


def upsert_instrument(db: Session, provider: str, ref: InstrumentRef) -> Instrument:
    inst = find_instrument(db, provider, ref.symbol)
    if inst is None:
        inst = Instrument(provider=provider, symbol=ref.symbol)
        db.add(inst)
    apply_ref(inst, ref, provider)
    db.flush()
    ensure_identifier(db, inst, provider, ref.symbol, f"{provider} symbol verified by quote")
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
            "exchange_code": inst.exchange_code,
            "mic": inst.mic,
            "country": inst.country,
            "identity_verified": inst.identity_verified_at is not None,
        }
    if fallback is not None:
        return {**fallback.to_dict(), "identity_verified": bool(fallback.currency)}
    return {
        "symbol": symbol,
        "name": None,
        "exchange": None,
        "currency": None,
        "timezone": None,
        "kind": None,
        "exchange_code": None,
        "mic": None,
        "country": None,
        "identity_verified": False,
    }


def validate_symbol(market: MarketDataService, symbol: str) -> str:
    try:
        return market.validate_symbol(symbol)
    except ProviderError as err:
        raise AppError(422, "unsupported_symbol", err.message) from err


async def resolve_instrument(db: Session, market: MarketDataService, symbol: str) -> Instrument:
    """Return a registered instrument, verifying unknown symbols with the provider first."""
    sym = validate_symbol(market, symbol)
    existing = find_instrument(db, market.source, sym)
    if existing is not None and existing.currency and existing.identity_verified_at is not None:
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
            suggestion = await _exchange_hint(market, sym)
            if suggestion:
                suggested, label = suggestion
                raise AppError(
                    422,
                    "symbol_unverified",
                    f"{sym} is not a Yahoo symbol. Did you mean {label}?",
                    {"suggestions": [suggested]},
                )
            raise AppError(status, "symbol_unverified", f"Could not verify {sym}: {reason}")
    inst = upsert_instrument(db, market.source, ref)
    db.commit()
    return inst


_BARE = re.compile(r"^[A-Z0-9&-]{1,20}$")


async def _exchange_hint(market: MarketDataService, sym: str) -> tuple[str, str] | None:
    """For a bare name like RELIANCE, return (symbol, label) of the NSE or BSE listing if one exists."""
    if market.source != "yahoo" or not _BARE.match(sym):
        return None
    for suffix, venue in ((".NS", "NSE"), (".BO", "BSE")):
        candidate = await market.quote(sym + suffix)
        if candidate.value is not None:
            name = candidate.value.instrument.name
            return sym + suffix, f"{sym}{suffix} ({venue}{', ' + name if name else ''})"
    return None
