#!/usr/bin/env python3
"""Memory soak test (docs/PERFORMANCE_ROADMAP.md 0.3).

Calls the API endpoints the instrument pages use, for many companies, against a running MarketDesk server, and
reports the web process's resident memory from /api/status after each company. Fails (exit 1) when the
web process ends above --web-limit MB, or keeps growing after the first --warmup companies.

    # terminal 1 (production-like, live data, local only):
    cd apps/api && DEV_AUTH_BYPASS=true DATA_PROVIDER=yahoo uv run python -m marketdesk.serve
    # terminal 2:
    python3 scripts/memory_soak.py --base http://127.0.0.1:8000

Standard library only. Development servers with DEV_AUTH_BYPASS need no login.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SYMBOLS = ["AAPL", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS",
           "ITC.NS", "SBIN.NS", "TSLA", "JPM", "ICICIBANK.NS", "LT.NS", "WMT", "KO", "BHARTIARTL.NS", "HINDUNILVR.NS",
           "NFLX", "AMD", "ASIANPAINT.NS", "MARUTI.NS"]  # fmt: skip
ENDPOINTS = [
    "/api/market/snapshots?symbols={s}",
    "/api/market/history?symbol={s}&range=1Y",
    "/api/market/history?symbol={s}&range=5Y",
    "/api/market/intraday?symbol={s}&range=1D",
    "/api/market/fundamentals?symbol={s}",
    "/api/market/actions?symbol={s}",
    "/api/terminal/description?symbol={s}",
    "/api/terminal/financial-analysis?symbol={s}",
    "/api/terminal/news?symbol={s}",
    "/api/terminal/events?symbol={s}",
    "/api/terminal/ownership?symbol={s}",
    "/api/terminal/options?symbol={s}",
    "/api/terminal/risk?symbol={s}",
    "/api/terminal/performance?symbol={s}",
    "/api/terminal/dividends?symbol={s}",
    "/api/earnings/{s}",
    "/api/screener/peers/{s}",
]


def get(base: str, path: str, timeout: float = 120) -> tuple[int, float, bytes]:
    started = time.monotonic()
    try:
        with urllib.request.urlopen(base + path, timeout=timeout) as r:  # noqa: S310 (local test server)
            return r.status, time.monotonic() - started, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, time.monotonic() - started, b""
    except (urllib.error.URLError, TimeoutError):
        return 0, time.monotonic() - started, b""


def memory(base: str) -> dict:
    code, _, body = get(base, "/api/status")
    if code != 200:
        return {}
    return (json.loads(body).get("memory") or {}).get("web") or {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--count", type=int, default=len(SYMBOLS))
    ap.add_argument("--web-limit", type=float, default=300.0, help="fail if the web process ends above this (MB)")
    ap.add_argument("--warmup", type=int, default=6, help="companies before growth must level off")
    args = ap.parse_args()

    start = memory(args.base).get("rss_mb")
    if start is None:
        print("Cannot read /api/status memory; is the server running (with this version)?")
        return 2
    print(f"web memory at start: {start} MB")
    readings, slow = [], []
    for i, sym in enumerate(SYMBOLS[: args.count], start=1):
        for ep in ENDPOINTS:
            path = ep.format(s=urllib.parse.quote(sym, safe=""))
            code, secs, _ = get(args.base, path)
            if secs > 2:
                slow.append((round(secs, 1), path, code))
        mem = memory(args.base)
        readings.append(mem.get("rss_mb", 0))
        print(f"{i:>2} {sym:<14} web {mem.get('rss_mb')} MB (peak {mem.get('peak_mb')})")
    end, peak = readings[-1], max(readings)
    after_warmup = readings[args.warmup - 1] if len(readings) >= args.warmup else readings[0]
    growth = end - after_warmup
    print(f"\nweb memory: start {start} → end {end} MB; peak {peak} MB; growth after warm-up {growth:+.1f} MB")
    if slow:
        print("slowest calls (> 2 s):")
        for s in sorted(slow, reverse=True)[:10]:
            print(f"  {s[0]:>5}s  {s[2]}  {s[1]}")
    ok = end <= args.web_limit and growth <= 40
    print("PASS" if ok else f"FAIL (limit {args.web_limit} MB, growth after warm-up must be ≤ 40 MB)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
