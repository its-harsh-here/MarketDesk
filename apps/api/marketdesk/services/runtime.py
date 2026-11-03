"""Construct the configured provider and market service (shared by web, worker and CLI)."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from marketdesk.config import Settings
from marketdesk.providers.fixture import FixtureProvider
from marketdesk.services.market import MarketDataService
from marketdesk.services.prefs import fixture_state_getter


def build_provider(settings: Settings):
    if settings.data_provider == "fixture":
        return FixtureProvider(settings.fixtures_dir, fixture_state_getter)
    from marketdesk.providers.yahoo import YahooProvider

    return YahooProvider(timeout=min(10.0, settings.provider_timeout_seconds),
                         cache_dir=settings.data_dir / "yfinance-cache")


def build_market_service(settings: Settings, sf: sessionmaker[Session] | None) -> MarketDataService:
    return MarketDataService(build_provider(settings), settings, sf)
