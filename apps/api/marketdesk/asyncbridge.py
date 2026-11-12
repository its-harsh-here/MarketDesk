"""Keep blocking database work off the server's event loop.

Several request handlers are coroutines because they await market data, but they also use the
synchronous SQLAlchemy session. Run on the server's event loop, every database round trip
(~100 ms when the database is hosted in another region) would freeze all other requests, so a page
that issues ten requests in parallel would be served one after another.

`off_event_loop` runs such a handler on a private event loop in a worker thread, so its database
calls only block that thread. Market-data calls made from there are forwarded to the server's loop
(`run_on_home_loop`), where the shared cache, request de-duplication and circuit breakers live.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import anyio.to_thread

_home_loop: asyncio.AbstractEventLoop | None = None


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def home_loop() -> asyncio.AbstractEventLoop | None:
    loop = _home_loop
    if loop is None or loop.is_closed() or not loop.is_running():
        return None
    return loop


async def run_on_home_loop[T](factory: Callable[[], Awaitable[T]]) -> T:
    """Await `factory()` on the server's event loop, from whichever loop is running now."""
    home = home_loop()
    if home is None or _running_loop() is home:
        return await factory()
    return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(factory(), home))


def off_event_loop[T](handler: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """Decorator for async FastAPI handlers that use the synchronous database session."""

    @functools.wraps(handler)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        global _home_loop
        _home_loop = asyncio.get_running_loop()
        return await anyio.to_thread.run_sync(functools.partial(_run, handler, args, kwargs))

    return wrapper


class _SharedExecutor(ThreadPoolExecutor):
    """One small pool shared by every request loop. asyncio.Runner shuts its loop's default executor down on exit;
    for the shared pool that is a no-op, so threads are reused instead of created per request (thread churn makes
    glibc keep per-thread memory arenas, which is where much of the process growth came from)."""

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:  # noqa: ARG002
        return None


SHARED_EXECUTOR = _SharedExecutor(max_workers=6, thread_name_prefix="blocking")


def configure_threads(n: int) -> None:
    """Size the shared pool and anyio's thread limiter (blocking routes) for this process."""
    SHARED_EXECUTOR._max_workers = max(2, n)  # noqa: SLF001 - sized once at startup, before use
    try:
        anyio.to_thread.current_default_thread_limiter().total_tokens = max(2, n)
    except RuntimeError:  # no running event loop yet: called again from the app's lifespan
        pass


def _run[T](handler: Callable[..., Awaitable[T]], args: tuple, kwargs: dict) -> T:
    with asyncio.Runner() as runner:
        runner.get_loop().set_default_executor(SHARED_EXECUTOR)
        return runner.run(handler(*args, **kwargs))  # type: ignore[arg-type]
