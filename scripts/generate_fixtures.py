#!/usr/bin/env python3
"""Generate the deterministic synthetic market dataset committed under fixtures/market.

Every company here is fictitious. Symbols use the ``SX:`` namespace on the imaginary
"SAMPLEX" exchange so they can never be confused with real listings. The dataset ends
at a fixed base date plus a few "replay" sessions used to step observations forward in
tests (e.g. to trigger a price alert). Timestamps are never moved to the present.

Usage:  python scripts/generate_fixtures.py [--out fixtures/market]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SEED = 20260630
START = date(2021, 7, 1)
BASE_DATE = date(2026, 6, 30)
REPLAY_SESSIONS = 5
# Synthetic calendar: weekdays except three fixed annual holidays. Not a real exchange calendar.
FIXED_HOLIDAYS = {(1, 26), (8, 15), (10, 2)}

EQUITIES = [
    # symbol, name, sector, industry, start, drift, vol, shares (mn), eps, bvps, annual div/share, avg vol
    ("AURORA", "Aurora Grid Power Ltd", "Utilities", "Power Generation", 212.0, 0.14, 0.24, 1900, 14.2, 96.0, 4.0, 2_400_000),
    ("BANYAN", "Banyan Retail Holdings Ltd", "Consumer Cyclical", "Department Stores", 1340.0, 0.09, 0.27, 410, 41.5, 260.0, 9.0, 650_000),
    ("COBALT", "Cobalt Infrastructure Ltd", "Industrials", "Engineering & Construction", 880.0, 0.16, 0.29, 820, 38.0, 310.0, 7.5, 980_000),
    ("DELTAFIN", "Deltaline Finance Ltd", "Financial Services", "Credit Services", 610.0, 0.11, 0.31, 1240, 33.0, 205.0, 5.0, 1_750_000),
    ("ELARA", "Elara Pharmaceuticals Ltd", "Healthcare", "Drug Manufacturers", 1820.0, 0.12, 0.23, 330, 62.0, 540.0, 12.0, 420_000),
    ("FERRUM", "Ferrum Steelworks Ltd", "Basic Materials", "Steel", 128.0, 0.06, 0.36, 5200, 9.1, 88.0, 2.5, 6_800_000),
    ("GLASSWING", "Glasswing Software Ltd", "Technology", "Information Technology Services", 2450.0, 0.13, 0.25, 290, 92.0, 410.0, 24.0, 520_000),
    ("HELIX", "Helix Biologics Ltd", "Healthcare", "Biotechnology", 540.0, 0.18, 0.42, 610, 6.5, 120.0, 0.0, 1_100_000),
    ("IRONLEAF", "Ironleaf Tea Estates Ltd", "Consumer Defensive", "Packaged Foods", 318.0, 0.05, 0.19, 720, 15.8, 132.0, 6.0, 380_000),
    ("KESTREL", "Kestrel Logistics Ltd", "Industrials", "Integrated Freight & Logistics", 760.0, 0.10, 0.28, 450, 27.0, 240.0, 3.0, 610_000),
    ("LUMEN", "Lumenfield Cement Ltd", "Basic Materials", "Building Materials", 4120.0, 0.08, 0.22, 95, 160.0, 1820.0, 35.0, 120_000),
    ("MERIDIAN", "Meridian Auto Components Ltd", "Consumer Cyclical", "Auto Parts", 965.0, 0.15, 0.30, 380, 36.0, 300.0, 8.0, 540_000),
    ("NIMBUS", "Nimbus Cloud Services Ltd", "Technology", "Software—Infrastructure", 690.0, 0.20, 0.45, 520, -4.2, None, 0.0, 1_350_000),
    ("ORCHID", "Orchid Hospitality Ltd", "Consumer Cyclical", "Lodging", 455.0, 0.12, 0.33, 680, 11.0, 150.0, 1.5, 890_000),
    ("PEREGRINE", "Peregrine Bank Ltd", "Financial Services", "Banks—Regional", 1510.0, 0.10, 0.26, 2100, 88.0, 640.0, 16.0, 2_900_000),
    ("QUILL", "Quillon Paper & Packaging Ltd", "Consumer Cyclical", "Packaging & Containers", 236.0, 0.02, 0.34, 260, 7.0, 140.0, 2.0, 300_000),
]
FINANCIALS = ("DELTAFIN", "PEREGRINE")
SPLITS = {"ELARA": (date(2024, 3, 15), 2)}  # 2-for-1; series is split-adjusted, like many providers
SUSPENDED = {"QUILL": date(2026, 6, 19)}  # no quotation after this session
COVERAGE_GAPS = {
    "NIMBUS": ["Price-to-book is not reported for this sample company."],
    "HELIX": ["Financial statement dates are not reported for this sample company."],
}
# Fixed replay returns for AURORA so alert tests have a known path after the base date.
AURORA_REPLAY_RETURNS = [0.024, 0.011, -0.006, 0.009, -0.015]


def is_session(d: date) -> bool:
    return d.weekday() < 5 and (d.month, d.day) not in FIXED_HOLIDAYS


def sessions_between(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if is_session(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def next_sessions(after: date, n: int) -> list[date]:
    out, d = [], after
    while len(out) < n:
        d += timedelta(days=1)
        if is_session(d):
            out.append(d)
    return out


def tick(x: float) -> float:
    return round(round(x * 20) / 20, 2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "fixtures" / "market"))
    out_dir = Path(parser.parse_args().out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(SEED)
    base_sessions = sessions_between(START, BASE_DATE)
    replay = next_sessions(BASE_DATE, REPLAY_SESSIONS)
    all_sessions = base_sessions + replay
    market_z = [rng.gauss(0, 1) for _ in all_sessions]

    rows: list[tuple] = []
    closes: dict[str, dict[date, float]] = {}
    instruments: list[dict] = []

    for sym, name, sector, industry, start, drift, vol, shares_mn, eps, bvps, div, avg_vol in EQUITIES:
        r = random.Random(f"{SEED}:{sym}")
        sd = vol / math.sqrt(252)
        mu = (drift - 0.5 * vol * vol) / 252
        price = start
        series: dict[date, float] = {}
        for i, d in enumerate(all_sessions):
            if sym in SUSPENDED and d > SUSPENDED[sym]:
                break
            z = 0.55 * market_z[i] + math.sqrt(1 - 0.55**2) * r.gauss(0, 1)
            ret = mu + sd * z
            if sym == "AURORA" and d in replay:
                ret = math.log1p(AURORA_REPLAY_RETURNS[replay.index(d)])
            prev = price
            close = tick(prev * math.exp(ret))
            open_ = tick(prev * math.exp(r.gauss(0, sd * 0.35)))
            high = tick(max(open_, close) * (1 + abs(r.gauss(0, sd * 0.45))))
            low = tick(min(open_, close) * (1 - abs(r.gauss(0, sd * 0.45))))
            volume = int(avg_vol * math.exp(r.gauss(0, 0.35)) * (1 + 2.5 * abs(ret) / sd * 0.3))
            rows.append((f"SX:{sym}", d.isoformat(), f"{open_:.2f}", f"{high:.2f}", f"{low:.2f}", f"{close:.2f}", volume))
            series[d] = close
            price = close
        closes[sym] = series
        actions = []
        if div > 0:
            for year in range(2022, 2027):
                ex = date(year, 6 if sym < "H" else 8, 12)
                while not is_session(ex):
                    ex += timedelta(days=1)
                if ex <= BASE_DATE:
                    actions.append({"date": ex.isoformat(), "kind": "DIVIDEND", "value": f"{div:.2f}",
                                    "description": f"Dividend of INR {div:.2f} per share (synthetic)"})
        if sym in SPLITS:
            sd_, ratio = SPLITS[sym]
            actions.append({"date": sd_.isoformat(), "kind": "SPLIT", "value": str(ratio),
                            "description": f"{ratio}-for-1 stock split (synthetic); price series is split-adjusted"})
        actions.sort(key=lambda a: a["date"])
        instruments.append({
            "symbol": f"SX:{sym}", "name": name, "exchange": "SAMPLEX", "currency": "INR",
            "timezone": "Asia/Kolkata", "kind": "EQUITY", "sector": sector, "industry": industry,
            "shares_outstanding": shares_mn * 1_000_000, "eps_ttm": eps, "book_value_per_share": bvps,
            "fiscal": None if sym == "HELIX" else {"last_fiscal_year_end": "2026-03-31", "most_recent_quarter": "2026-03-31"},
            "coverage_notes": COVERAGE_GAPS.get(sym, []),
            "quote_status": "missing" if sym in SUSPENDED else "available",
            "quote_note": (f"Trading suspended after {SUSPENDED[sym].isoformat()} in this sample scenario; "
                           "no current quotation exists.") if sym in SUSPENDED else None,
            "corporate_actions": actions,
        })

    # Non-INR sample instrument (researchable, cannot be held in the INR portfolio).
    r = random.Random(f"{SEED}:HALCYON")
    price, sd = 48.0, 0.38 / math.sqrt(252)
    ny = ZoneInfo("America/New_York")
    for i, d in enumerate(all_sessions):
        ret = 0.0004 + sd * (0.3 * market_z[i] + 0.95 * r.gauss(0, 1))
        close = round(price * math.exp(ret), 2)
        open_ = round(price * math.exp(r.gauss(0, sd * 0.3)), 2)
        high = round(max(open_, close) * (1 + abs(r.gauss(0, sd * 0.4))), 2)
        low = round(min(open_, close) * (1 - abs(r.gauss(0, sd * 0.4))), 2)
        rows.append(("SX:HALCYON", d.isoformat(), f"{open_:.2f}", f"{high:.2f}", f"{low:.2f}", f"{close:.2f}",
                     int(3_200_000 * math.exp(r.gauss(0, 0.3)))))
        price = close
    instruments.append({
        "symbol": "SX:HALCYON", "name": "Halcyon Robotics Inc.", "exchange": "SAMPLEX-US", "currency": "USD",
        "timezone": "America/New_York", "kind": "EQUITY", "sector": "Technology", "industry": "Robotics",
        "shares_outstanding": 410_000_000, "eps_ttm": 1.12, "book_value_per_share": 9.4,
        "fiscal": {"last_fiscal_year_end": "2025-12-31", "most_recent_quarter": "2026-03-31"},
        "coverage_notes": [], "quote_status": "available", "quote_note": None, "corporate_actions": [],
        "close_time": {"hour": 16, "minute": 0},
    })
    _ = ny

    # Synthetic USD/INR rate (INR per USD) for valuing the sample USD account. Fictitious, like every series here.
    r = random.Random(f"{SEED}:USDINR")
    rate, sd = 82.0, 0.045 / math.sqrt(252)
    for d in all_sessions:
        close = round(rate * math.exp(0.00008 + r.gauss(0, sd)), 4)
        open_ = round(rate * math.exp(r.gauss(0, sd * 0.3)), 4)
        high = round(max(open_, close) * (1 + abs(r.gauss(0, sd * 0.3))), 4)
        low = round(min(open_, close) * (1 - abs(r.gauss(0, sd * 0.3))), 4)
        rows.append(("SX:USDINR", d.isoformat(), f"{open_:.4f}", f"{high:.4f}", f"{low:.4f}", f"{close:.4f}", ""))
        rate = close
    instruments.append({
        "symbol": "SX:USDINR", "name": "Sample USD/INR rate (synthetic)", "exchange": "SAMPLEX-FX", "currency": "INR",
        "timezone": "Asia/Kolkata", "kind": "CURRENCY", "sector": None, "industry": None, "shares_outstanding": None,
        "eps_ttm": None, "book_value_per_share": None, "fiscal": None,
        "coverage_notes": ["A synthetic exchange rate (INR per USD) for the sample dataset; not a real quotation."],
        "quote_status": "available", "quote_note": None, "corporate_actions": [],
    })

    # Equal-weight indices built from component returns.
    def build_index(sym: str, name: str, members: list[str], base: float) -> None:
        level = base
        prev_close: dict[str, float] = {}
        r = random.Random(f"{SEED}:{sym}")
        for d in all_sessions:
            rets = []
            for m in members:
                c = closes[m].get(d)
                if c is not None and m in prev_close:
                    rets.append(c / prev_close[m] - 1)
                if c is not None:
                    prev_close[m] = c
            prev = level
            if rets:
                level = level * (1 + sum(rets) / len(rets))
            close = round(level, 2)
            open_ = round(prev * (1 + r.gauss(0, 0.0015)), 2)
            high = round(max(open_, close) * (1 + abs(r.gauss(0, 0.002))), 2)
            low = round(min(open_, close) * (1 - abs(r.gauss(0, 0.002))), 2)
            rows.append((f"SX:{sym}", d.isoformat(), f"{open_:.2f}", f"{high:.2f}", f"{low:.2f}", f"{close:.2f}", ""))
        instruments.append({
            "symbol": f"SX:{sym}", "name": name, "exchange": "SAMPLEX", "currency": "INR", "timezone": "Asia/Kolkata",
            "kind": "INDEX", "sector": None, "industry": None, "shares_outstanding": None, "eps_ttm": None,
            "book_value_per_share": None, "fiscal": None,
            "coverage_notes": ["Fundamentals are not applicable to an index.", "Index volume is not reported."],
            "quote_status": "available", "quote_note": None, "corporate_actions": [],
        })

    inr_members = [e[0] for e in EQUITIES if e[0] not in SUSPENDED]
    build_index("SX50", "SampleX Composite Index", inr_members, 10000.0)
    build_index("SXFIN", "SampleX Financials Index", list(FINANCIALS), 5000.0)

    rows.sort(key=lambda t: (t[0], t[1]))
    with (out_dir / "daily_bars.csv").open("w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["symbol", "date", "open", "high", "low", "close", "volume"])
        w.writerows(rows)

    meta = {
        "dataset": {
            "name": "MarketDesk synthetic sample dataset",
            "disclaimer": ("All companies, symbols, prices and fundamentals in this dataset are fictitious and "
                           "generated deterministically. They do not represent any real security."),
            "base_date": BASE_DATE.isoformat(),
            "replay_sessions": [d.isoformat() for d in replay],
            "first_date": START.isoformat(),
            "calendar": "Synthetic: weekdays except 26 Jan, 15 Aug and 2 Oct. Not a real exchange calendar.",
            "close_time_local": "15:30",
            "adjustment": "Split-adjusted synthetic series; dividends are not adjusted.",
            "seed": SEED,
            "generator": "scripts/generate_fixtures.py",
            "generated_at": datetime.combine(BASE_DATE, time(0, 0)).isoformat() + "Z",
        },
        "benchmarks": ["SX:SX50", "SX:SXFIN"],
        "starter_watchlist": [f"SX:{e[0]}" for e in EQUITIES[:12]],
        "instruments": sorted(instruments, key=lambda i: i["symbol"]),
    }
    (out_dir / "instruments.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {len(rows)} bars for {len(instruments)} instruments to {out_dir}")


if __name__ == "__main__":
    main()
