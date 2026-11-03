#!/usr/bin/env python3
"""Live smoke test of the YahooProvider through the MarketDesk market service.

Usage (from apps/api):  uv run python ../../scripts/check_yahoo.py [SYMBOL ...]
Prints one line per check with the freshness status, market time and a key value.
Network access to Yahoo is required; results depend on Yahoo availability and rate limits.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from marketdesk.config import Settings  # noqa: E402
from marketdesk.providers.yahoo import YahooProvider  # noqa: E402
from marketdesk.services.market import MarketDataService  # noqa: E402


async def main(symbols: list[str]) -> int:
    tmp = Path(tempfile.mkdtemp())
    settings = Settings(data_provider="yahoo", data_dir=tmp)
    svc = MarketDataService(YahooProvider(timeout=10, cache_dir=tmp / "yf"), settings, None)
    failures = 0

    def report(label: str, result, value: str) -> None:
        nonlocal failures
        m = result.meta
        ok = result.value is not None
        failures += 0 if ok else 1
        print(f"{'OK  ' if ok else 'FAIL'} {label:<28} status={m.status:<11} market_time={m.market_time} "
              f"ccy={m.currency} {value if ok else (m.error_kind, m.message)}")

    s = await svc.search("Reliance Industries", 5)
    report("search 'Reliance Industries'", s, [r.symbol for r in (s.value or [])][:5])
    for sym in symbols:
        q = await svc.quote(sym)
        v = q.value
        report(f"quote {sym}", q, f"last={v.last_price} prev={v.previous_close} chg%={v.change_percent and round(v.change_percent, 2)} "
                                  f"vol={v.volume} session={v.session_date} bars={len(v.recent_bars)}" if v else "")
    h = await svc.history(symbols[0], "1Y")
    report(f"history {symbols[0]} 1Y", h, f"bars={len(h.value.bars)} first={h.value.bars[0].session_date} "
                                           f"last={h.value.bars[-1].session_date}" if h.value else "")
    f = await svc.fundamentals(symbols[0])
    report(f"fundamentals {symbols[0]}", f, f"mcap={f.value.market_cap} pe={f.value.pe_ratio} "
                                            f"dy%={f.value.dividend_yield_percent} mrq={f.value.most_recent_quarter}" if f.value else "")
    a = await svc.actions(symbols[0])
    report(f"actions {symbols[0]}", a, f"{len(a.value)} actions, latest={a.value[0] if a.value else None}" if a.value is not None else "")
    print("failures:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    syms = sys.argv[1:] or ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ITC.NS", "^NSEI"]
    raise SystemExit(asyncio.run(main(syms)))
