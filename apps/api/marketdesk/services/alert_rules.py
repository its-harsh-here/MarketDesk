"""Pure alert-rule logic (no I/O), unit-tested on edge cases.

Granularity per rule:
- PRICE: each new sampled quote observation (keyed by market time). Fires when price >= / <= target.
- CROSS: each new sampled observation. Fires only when the price moves from one side of the level to the other
  between two consecutive observations; the first observation after arming is only a baseline.
- VOLUME: completed daily sessions only. Fires when a session's volume >= multiple x the average volume of the
  `lookback` completed sessions before it. An unfinished session is never compared with full days.
- VOLATILITY: completed daily sessions only. Fires when |daily close-to-close return| >= multiple x the standard
  deviation of the previous `lookback` daily returns.
- FILING: new SEC filings (US listings) of the chosen forms, checked with the research service.
Missing data policy (all rules): if the required data is missing, stale, or there are too few comparable sessions,
the rule is not evaluated and the reason is recorded; missing values are never treated as zero.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from statistics import mean, pstdev
from zoneinfo import ZoneInfo

RULES = ("PRICE", "CROSS", "VOLUME", "VOLATILITY", "FILING")
FILING_FORMS = ("10-K", "10-Q", "8-K", "20-F", "6-K", "DEF 14A")


def plain(value: Decimal) -> str:
    """A multiple or ratio without storage padding (PostgreSQL NUMERIC returns trailing zeros): 2.000 -> "2"."""
    return format(Decimal(value).normalize(), "f")


def price_text(value: Decimal) -> str:
    """A price with 2 to 4 decimals, the same on every database: 169.800000 -> "169.80", 1.23456 -> "1.2346"."""
    v = Decimal(value).normalize()
    exp = v.as_tuple().exponent
    return f"{v:,.{max(2, min(-exp if isinstance(exp, int) and exp < 0 else 0, 4))}f}"


def day_text(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def crossed(direction: str, level: Decimal, previous: Decimal | None, price: Decimal) -> bool:
    if previous is None:
        return False  # baseline only
    if direction == "ABOVE":
        return previous < level <= price
    return previous > level >= price


def completed_bars(bars: list, last_session_complete: bool) -> list:
    """Drop the latest bar when its session may still be trading (calendar says open/unknown for that day)."""
    return list(bars) if last_session_complete else list(bars[:-1])


def volume_signal(bars: list, lookback: int, multiple: Decimal):
    """bars: completed sessions, oldest first, each with .session_date and .volume.
    Returns (session_date, fired, explanation) for the latest session, or (None, False, reason) when not evaluable."""
    if len(bars) < lookback + 1:
        return None, False, f"Needs {lookback + 1} completed sessions; {len(bars)} available."
    latest, window = bars[-1], bars[-(lookback + 1) : -1]
    if latest.volume is None or any(b.volume is None for b in window):
        return None, False, "Volume is not reported for some of the comparable sessions."
    avg = Decimal(str(mean(b.volume for b in window)))
    if avg <= 0:
        return None, False, "Average volume of the comparison window is zero."
    ratio = Decimal(latest.volume) / avg
    text = (
        f"Volume {latest.volume:,} on {day_text(latest.session_date)} was {ratio:.2f}x the {lookback}-session "
        f"average ({avg:,.0f}); threshold {plain(multiple)}x. Completed sessions only."
    )
    return latest.session_date, ratio >= multiple, text


def volatility_signal(bars: list, lookback: int, multiple: Decimal):
    if len(bars) < lookback + 2:
        return None, False, f"Needs {lookback + 2} completed sessions; {len(bars)} available."
    closes = [b.close for b in bars]
    if any(c is None or c <= 0 for c in closes[-(lookback + 2) :]):
        return None, False, "Some closing prices in the comparison window are missing."
    rets = [float(closes[i] / closes[i - 1] - 1) for i in range(len(closes) - lookback - 1, len(closes))]
    window, latest = rets[:-1], rets[-1]
    sd = pstdev(window)
    if sd == 0:
        return None, False, "Returns in the comparison window do not vary."
    score = abs(latest) / sd
    text = (
        f"Daily return {latest * 100:+.2f}% on {day_text(bars[-1].session_date)} was {score:.2f} standard "
        f"deviations of the previous {lookback} sessions' returns (sd {sd * 100:.2f}%); threshold {plain(multiple)}. "
        "Completed sessions only."
    )
    return bars[-1].session_date, Decimal(str(score)) >= multiple, text


def _hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def valid_hhmm(value: str | None) -> bool:
    try:
        return value is not None and len(value) == 5 and 0 <= _hhmm(value).hour < 24
    except (ValueError, AttributeError):
        return False


def quiet_release(now: datetime, start: str | None, end: str | None, tz: str) -> datetime | None:
    """If `now` falls in the quiet window [start, end) in timezone `tz`, return when it ends (UTC-aware); else None.
    Windows may span midnight (22:00-07:00). Daylight-saving changes are handled by zoneinfo."""
    if not (valid_hhmm(start) and valid_hhmm(end)) or start == end:
        return None
    zone = ZoneInfo(tz)
    local = now.astimezone(zone)
    s, e, t = _hhmm(start), _hhmm(end), local.time()
    inside = (s <= t < e) if s < e else (t >= s or t < e)
    if not inside:
        return None
    end_day: date = local.date() if (s < e or t < e) else local.date() + timedelta(days=1)
    return datetime.combine(end_day, e, tzinfo=zone).astimezone(now.tzinfo or ZoneInfo("UTC"))
