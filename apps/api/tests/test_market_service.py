"""Cache, stale fallback, circuit breaker, de-duplication and timeout behaviour."""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, date, datetime
from decimal import Decimal

from marketdesk.db import init_engine, session_factory
from marketdesk.providers.base import InstrumentRef, ProviderError, QuoteSnapshot
from marketdesk.services.market import MarketDataService

from .conftest import make_settings, migrated

REF = InstrumentRef("TEST.NS", "Test Co", "NSE", "INR", "Asia/Kolkata", "EQUITY")


def snap(price="100"):
    return QuoteSnapshot(
        REF,
        Decimal(price),
        Decimal("99"),
        datetime(2026, 6, 30, 10, tzinfo=UTC),
        date(2026, 6, 30),
        None,
        None,
        10,
        None,
        [],
    )


class FakeProvider:
    name = "fake"
    is_sample = False

    def __init__(self):
        self.calls = 0
        self.fail: ProviderError | None = None
        self.delay = 0.0
        self.lock = threading.Lock()

    def cache_namespace(self):
        return "f"

    def validate_symbol(self, s):
        return s

    def quote(self, symbol):
        with self.lock:
            self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise self.fail
        return snap()


def service(tmp_path, persisted=True, **kw):
    s = migrated(make_settings(tmp_path, **kw))
    init_engine(s)
    p = FakeProvider()
    return MarketDataService(p, s, session_factory() if persisted else None, retry_base_delay=0), p


def test_fresh_then_cached_statuses(tmp_path):
    svc, p = service(tmp_path)
    first = asyncio.run(svc.quote("TEST.NS"))
    second = asyncio.run(svc.quote("TEST.NS"))
    assert first.meta.status == "available" and second.meta.status == "cached"
    assert p.calls == 1
    assert second.meta.market_time == first.meta.market_time  # cached != a new market observation


def test_stale_fallback_after_failure_keeps_last_value(tmp_path):
    svc, p = service(tmp_path, quote_ttl_seconds=0)
    asyncio.run(svc.quote("TEST.NS"))
    p.fail = ProviderError("upstream_unavailable", "HTTP 503", retryable=True)
    r = asyncio.run(svc.quote("TEST.NS"))
    assert r.meta.status == "stale"
    assert r.value.last_price == Decimal("100")
    assert "last successful" in r.meta.message
    assert r.meta.fetched_at is not None


def test_persisted_cache_survives_restart_as_stale(tmp_path):
    svc, p = service(tmp_path, quote_ttl_seconds=0)
    asyncio.run(svc.quote("TEST.NS"))
    svc2 = MarketDataService(p, svc.settings, session_factory(), retry_base_delay=0)  # new process, empty memory
    p.fail = ProviderError("rate_limited", "429", retryable=True)
    r = asyncio.run(svc2.quote("TEST.NS"))
    assert r.meta.status == "stale" and r.value is not None


def test_failure_without_cache_is_unavailable_not_zero(tmp_path):
    svc, p = service(tmp_path, persisted=False)
    p.fail = ProviderError("upstream_unavailable", "down", retryable=True)
    r = asyncio.run(svc.quote("TEST.NS"))
    assert r.value is None and r.meta.status == "unavailable" and r.meta.error_kind == "upstream_unavailable"


def test_missing_is_reported_and_negatively_cached(tmp_path):
    svc, p = service(tmp_path, persisted=False)
    p.fail = ProviderError("missing", "no data")
    assert asyncio.run(svc.quote("TEST.NS")).meta.status == "missing"
    assert asyncio.run(svc.quote("TEST.NS")).meta.status == "missing"
    assert p.calls == 1


def test_retries_are_bounded(tmp_path):
    svc, p = service(tmp_path, persisted=False, provider_max_retries=2)
    p.fail = ProviderError("rate_limited", "429", retryable=True)
    asyncio.run(svc.quote("TEST.NS"))
    assert p.calls == 3


def test_circuit_opens_after_repeated_failures(tmp_path):
    svc, p = service(
        tmp_path, persisted=False, provider_max_retries=0, circuit_failure_threshold=2, quote_ttl_seconds=0
    )
    p.fail = ProviderError("upstream_unavailable", "down", retryable=True)
    asyncio.run(svc.quote("A"))
    asyncio.run(svc.quote("B"))
    assert svc.health()["circuit"] == "open"
    calls = p.calls
    r = asyncio.run(svc.quote("C"))
    assert p.calls == calls and r.meta.status == "unavailable" and "paused" in r.meta.message


def test_concurrent_requests_are_deduplicated(tmp_path):
    svc, p = service(tmp_path, persisted=False)
    p.delay = 0.2

    async def many():
        return await asyncio.gather(*(svc.quote("TEST.NS") for _ in range(5)))

    results = asyncio.run(many())
    assert p.calls == 1 and all(r.value is not None for r in results)


def test_timeout_becomes_structured_error(tmp_path):
    svc, p = service(tmp_path, persisted=False, provider_timeout_seconds=0.05, provider_max_retries=0)
    p.delay = 0.3
    r = asyncio.run(svc.quote("TEST.NS"))
    assert r.meta.status == "unavailable" and r.meta.error_kind == "timeout"


def test_memory_cache_is_bounded(tmp_path):
    svc, _ = service(tmp_path, persisted=False, memory_cache_entries=3)
    for s in "ABCDE":
        asyncio.run(svc.quote(s))
    assert len(svc._mem) == 3


def test_fundamentals_failures_do_not_pause_quotes(tmp_path):
    svc, p = service(tmp_path, persisted=False, provider_max_retries=0, circuit_failure_threshold=2)

    def refused(symbol):
        raise ProviderError("upstream_unavailable", "HTTP 503", retryable=True)

    p.fundamentals = refused
    for sym in ("A", "B", "C"):
        assert asyncio.run(svc.fundamentals(sym)).meta.status == "unavailable"
    health = svc.health()
    assert health["endpoints"]["fundamentals"]["circuit"] == "open"
    assert health["circuit"] == "closed"  # prices unaffected
    assert asyncio.run(svc.quote("TEST.NS")).meta.status == "available"


def test_non_transient_errors_never_open_the_circuit(tmp_path):
    svc, p = service(tmp_path, persisted=False, provider_max_retries=0, circuit_failure_threshold=2)
    p.fail = ProviderError("upstream_unavailable", "HTTP 401 for an unknown symbol", retryable=False)
    for sym in ("X1", "X2", "X3", "X4"):
        asyncio.run(svc.quote(sym))
    assert svc.health()["circuit"] == "closed"
