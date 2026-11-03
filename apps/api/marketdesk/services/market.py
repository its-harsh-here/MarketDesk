"""Market data service: caching, request de-duplication, retries, circuit breaker and
explicit freshness metadata around a MarketDataProvider.

Freshness statuses
  sample       fixture data (never live)
  available    fetched from the provider for this request
  cached       served from cache within its TTL (a recent fetch, not proof of a fresh quotation)
  stale        the provider failed; showing the last successful result with its fetch time
  missing      the provider has no data for this request
  unsupported  the symbol/feature is not supported by this provider
  unavailable  the provider failed and nothing usable is cached
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Generic, Literal, TypeVar

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from marketdesk.asyncbridge import run_on_home_loop
from marketdesk.config import Settings
from marketdesk.models import MarketCacheEntry
from marketdesk.providers.base import (
    CorporateAction,
    Fundamentals,
    HistoryRange,
    InstrumentRef,
    PriceHistory,
    ProviderError,
    QuoteSnapshot,
)
from marketdesk.providers.serialize import CODECS

log = logging.getLogger("marketdesk.market")
T = TypeVar("T")
CIRCUIT_GROUPS = {
    "quote": "prices",
    "history": "prices",
    "actions": "prices",
    "fundamentals": "fundamentals",
    "search": "search",
}
Status = Literal["sample", "available", "cached", "stale", "missing", "unsupported", "unavailable"]


@dataclass
class DataMeta:
    source: str
    status: Status
    fetched_at: datetime | None = None
    market_time: datetime | None = None
    currency: str | None = None
    timezone: str | None = None
    message: str | None = None
    error_kind: str | None = None

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "status": self.status,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "market_time": self.market_time.isoformat() if self.market_time else None,
            "currency": self.currency,
            "timezone": self.timezone,
            "message": self.message,
            "error_kind": self.error_kind,
        }


@dataclass
class Result(Generic[T]):
    value: T | None
    meta: DataMeta

    @property
    def usable(self) -> bool:
        return self.value is not None


@dataclass
class _MemEntry:
    value: Any
    fetched_at: datetime
    expires_at: float  # monotonic
    error: ProviderError | None = None


@dataclass
class CircuitBreaker:
    threshold: int
    open_seconds: int
    failures: int = 0
    open_until: float = 0.0
    last_error: dict | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    clock: Callable[[], float] = field(default=time.monotonic)

    def allow(self) -> bool:
        return self.clock() >= self.open_until

    def state(self) -> str:
        if self.clock() < self.open_until:
            return "open"
        if self.failures >= self.threshold:
            return "half_open"
        return "closed"

    def record_success(self) -> None:
        self.failures = 0
        self.open_until = 0.0
        self.last_success_at = datetime.now(UTC)

    def record_failure(self, err: ProviderError) -> None:
        self.failures += 1
        self.last_error = err.to_dict()
        self.last_failure_at = datetime.now(UTC)
        if self.failures >= self.threshold:
            self.open_until = self.clock() + self.open_seconds


class MarketDataService:
    def __init__(
        self,
        provider: Any,
        settings: Settings,
        session_factory: sessionmaker[Session] | None = None,
        retry_base_delay: float = 0.5,
    ):
        self.provider = provider
        self.settings = settings
        self._sf = session_factory
        self._retry_base_delay = retry_base_delay
        self._mem: OrderedDict[str, _MemEntry] = OrderedDict()
        self._inflight: dict[str, asyncio.Future] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, settings.provider_max_concurrency), thread_name_prefix="provider"
        )
        # One breaker per endpoint family, so e.g. a refused fundamentals endpoint can never pause quotes.
        self.circuits = {
            group: CircuitBreaker(settings.circuit_failure_threshold, settings.circuit_open_seconds)
            for group in set(CIRCUIT_GROUPS.values())
        }
        self._writes = 0
        self.ttl = {
            "quote": settings.quote_ttl_seconds,
            "history": settings.history_ttl_seconds,
            "fundamentals": settings.fundamentals_ttl_seconds,
            "actions": settings.fundamentals_ttl_seconds,
            "search": settings.search_ttl_seconds,
        }

    # ------------------------------------------------------------------ public API
    @property
    def source(self) -> str:
        return self.provider.name

    def validate_symbol(self, symbol: str) -> str:
        return self.provider.validate_symbol(symbol)

    async def quote(self, symbol: str) -> Result[QuoteSnapshot]:
        return await self._get("quote", symbol, lambda: self.provider.quote(symbol))

    async def quotes(self, symbols: list[str]) -> dict[str, Result[QuoteSnapshot]]:
        unique = list(dict.fromkeys(symbols))
        results = await asyncio.gather(*(self.quote(s) for s in unique))
        return dict(zip(unique, results, strict=True))

    async def history(self, symbol: str, range_: HistoryRange) -> Result[PriceHistory]:
        return await self._get("history", f"{symbol}|{range_}", lambda: self.provider.history(symbol, range_))

    async def fundamentals(self, symbol: str) -> Result[Fundamentals]:
        return await self._get("fundamentals", symbol, lambda: self.provider.fundamentals(symbol))

    async def actions(self, symbol: str) -> Result[list[CorporateAction]]:
        return await self._get("actions", symbol, lambda: self.provider.corporate_actions(symbol))

    async def search(self, query: str, limit: int) -> Result[list[InstrumentRef]]:
        q = " ".join(query.split()).lower()[:64]
        return await self._get("search", f"{q}|{limit}", lambda: self.provider.search(q, limit))

    def invalidate(self) -> None:
        self._mem.clear()

    @property
    def circuit(self) -> CircuitBreaker:
        """The price-data breaker (quotes, history, corporate actions) — what most screens depend on."""
        return self.circuits["prices"]

    def reset_circuit(self) -> None:
        for c in self.circuits.values():
            c.failures = 0
            c.open_until = 0.0

    def health(self) -> dict:
        c = self.circuit
        return {
            "provider": self.provider.name,
            "sample": bool(self.provider.is_sample),
            "circuit": c.state(),
            "consecutive_failures": c.failures,
            "last_success_at": c.last_success_at.isoformat() if c.last_success_at else None,
            "last_failure_at": c.last_failure_at.isoformat() if c.last_failure_at else None,
            "last_error": c.last_error,
            "endpoints": {
                group: {"circuit": b.state(), "consecutive_failures": b.failures, "last_error": b.last_error}
                for group, b in sorted(self.circuits.items())
            },
        }

    # ------------------------------------------------------------------ internals
    def _key(self, kind: str, ident: str) -> str:
        ns = self.provider.cache_namespace() if hasattr(self.provider, "cache_namespace") else ""
        return f"{kind}:{self.provider.name}:{ns}:{ident}"

    def _meta_for(self, kind: str, value: Any, status: Status, fetched_at: datetime | None, message=None) -> DataMeta:
        if self.provider.is_sample and status in ("available", "cached"):
            status = "sample"
        meta = DataMeta(source=self.provider.name, status=status, fetched_at=fetched_at, message=message)
        inst = getattr(value, "instrument", None)
        if inst is not None:
            meta.currency, meta.timezone = inst.currency, inst.timezone
        if kind == "quote" and value is not None:
            meta.market_time = value.market_time
        return meta

    def _error_meta(self, err: ProviderError) -> DataMeta:
        status: Status
        if err.kind == "missing":
            status = "missing"
        elif err.kind == "unsupported":
            status = "unsupported"
        else:
            status = "unavailable"
        return DataMeta(source=self.provider.name, status=status, message=err.message, error_kind=err.kind)

    async def _get(self, kind: str, ident: str, fn: Callable[[], Any]) -> Result:
        # The cache, de-duplication and breakers belong to the server's event loop; handlers running
        # on a private loop (see marketdesk.asyncbridge) are forwarded there.
        return await run_on_home_loop(lambda: self._get_here(kind, ident, fn))

    def _key_and_bypass(self, kind: str, ident: str) -> tuple[str, bool]:
        try:
            key = self._key(kind, ident)
        except Exception as exc:  # fixture state read failure etc.
            log.warning("cache key failed: %s", type(exc).__name__)
            key = f"{kind}:{self.provider.name}:?:{ident}"
        # Fixture outage drills bypass fresh-cache shortcuts so the stale path is exercised.
        bypass = bool(getattr(self.provider, "simulating_outage", lambda: False)())
        return key, bypass

    async def _get_here(self, kind: str, ident: str, fn: Callable[[], Any]) -> Result:
        if self.provider.is_sample:
            # The fixture provider reads its replay state from the database: never on the event loop.
            key, bypass = await asyncio.to_thread(self._key_and_bypass, kind, ident)
        else:
            key, bypass = self._key_and_bypass(kind, ident)
        now_mono = time.monotonic()
        entry = self._mem.get(key)
        if entry is not None and entry.expires_at > now_mono and not bypass:
            self._mem.move_to_end(key)
            if entry.error is not None:
                return Result(None, self._error_meta(entry.error))
            return Result(entry.value, self._meta_for(kind, entry.value, "cached", entry.fetched_at))

        persisted = await asyncio.to_thread(self._persist_get, key, kind) if self._sf is not None else None
        if persisted is not None and not bypass:
            value, fetched_at = persisted
            age = (datetime.now(UTC) - fetched_at).total_seconds()
            if age < self.ttl[kind]:
                self._mem_put(key, _MemEntry(value, fetched_at, now_mono + (self.ttl[kind] - age)))
                return Result(value, self._meta_for(kind, value, "cached", fetched_at))

        if key in self._inflight:
            return await asyncio.shield(self._inflight[key])
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            result = await self._fetch(kind, key, fn, entry, persisted)
        except BaseException:  # pragma: no cover - _fetch converts provider failures into results
            fut.cancel()
            raise
        finally:
            self._inflight.pop(key, None)
        fut.set_result(result)
        return result

    async def _fetch(self, kind, key, fn, entry: _MemEntry | None, persisted) -> Result:
        circuit = self.circuits[CIRCUIT_GROUPS[kind]]
        try:
            if not circuit.allow():
                raise ProviderError(
                    "upstream_unavailable",
                    "Provider requests are paused briefly after repeated failures.",
                    retryable=False,
                )
            value = await self._run_with_retry(fn)
        except ProviderError as err:
            # Only transient failures (timeouts, 429, 5xx, network) trip the breaker; a refused or unknown
            # symbol is not an outage and must never pause every other request.
            if err.retryable and circuit.allow():
                circuit.record_failure(err)
            # Prefer the last successful value (explicitly stale) over an empty panel.
            fallback = None
            if entry is not None and entry.error is None:
                fallback = (entry.value, entry.fetched_at)
            elif persisted is not None:
                fallback = persisted
            if fallback is not None:
                value, fetched_at = fallback
                msg = f"Showing the last successful result. {err.message}"
                meta = self._meta_for(kind, value, "stale", fetched_at, message=msg)
                meta.status = "stale"
                meta.error_kind = err.kind
                return Result(value, meta)
            if err.kind in ("missing", "unsupported"):
                self._mem_put(key, _MemEntry(None, datetime.now(UTC), time.monotonic() + 300, error=err))
            return Result(None, self._error_meta(err))

        circuit.record_success()
        fetched_at = datetime.now(UTC)
        self._mem_put(key, _MemEntry(value, fetched_at, time.monotonic() + self.ttl[kind]))
        if self._sf is not None:
            await asyncio.to_thread(self._persist_put, key, kind, value, fetched_at)
        return Result(value, self._meta_for(kind, value, "available", fetched_at))

    async def _run_with_retry(self, fn: Callable[[], Any]) -> Any:
        loop = asyncio.get_running_loop()
        attempts = self.settings.provider_max_retries + 1
        for attempt in range(attempts):
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(self._executor, fn), timeout=self.settings.provider_timeout_seconds
                )
            except TimeoutError as exc:
                err = ProviderError("timeout", "The provider did not respond in time.", retryable=True)
                err.__cause__ = exc
            except ProviderError as exc:
                err = exc
            except Exception as exc:  # unexpected provider bug: treat as malformed, never crash the request
                log.warning("provider raised %s", type(exc).__name__)
                err = ProviderError("malformed", f"Provider error ({type(exc).__name__}).")
            if not err.retryable or attempt == attempts - 1:
                raise err
            delay = min(8.0, self._retry_base_delay * (2**attempt)) * (0.5 + random.random())
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def _mem_put(self, key: str, entry: _MemEntry) -> None:
        self._mem[key] = entry
        self._mem.move_to_end(key)
        while len(self._mem) > self.settings.memory_cache_entries:
            self._mem.popitem(last=False)

    def _persist_get(self, key: str, kind: str):
        if self._sf is None:
            return None
        try:
            with self._sf() as db:
                row = db.get(MarketCacheEntry, key)
                if row is None:
                    return None
                _, decode = CODECS[kind]
                return decode(row.payload), row.fetched_at
        except Exception as exc:  # cache must never break a request
            log.warning("persisted cache read failed: %s", type(exc).__name__)
            return None

    def _persist_put(self, key: str, kind: str, value: Any, fetched_at: datetime) -> None:
        if self._sf is None:
            return
        try:
            encode, _ = CODECS[kind]
            with self._sf() as db:
                db.merge(
                    MarketCacheEntry(
                        key=key,
                        kind=kind,
                        provider=self.provider.name,
                        payload=encode(value),
                        fetched_at=fetched_at,
                        last_access_at=datetime.now(UTC),
                    )
                )
                db.commit()
                self._writes += 1
                if self._writes % 50 == 0:
                    self._prune(db)
        except Exception as exc:
            log.warning("persisted cache write failed: %s", type(exc).__name__)

    def _prune(self, db: Session) -> None:
        limit = self.settings.persisted_cache_rows
        count = db.scalar(select(func.count()).select_from(MarketCacheEntry)) or 0
        if count <= limit:
            return
        cutoff_rows = db.scalars(
            select(MarketCacheEntry.key).order_by(MarketCacheEntry.last_access_at.asc()).limit(count - limit)
        ).all()
        db.execute(delete(MarketCacheEntry).where(MarketCacheEntry.key.in_(cutoff_rows)))
        db.execute(delete(MarketCacheEntry).where(MarketCacheEntry.fetched_at < datetime.now(UTC) - timedelta(days=30)))
        db.commit()
