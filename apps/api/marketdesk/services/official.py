"""Terminal T8: US official statistics from FRED with their release and revision dates, and an upcoming release
calendar. Each value carries its observation date, the vintage (the date FRED's current value became the latest
revision) and FRED's last-updated time. Nothing is estimated or interpolated."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from marketdesk.models import MarketCacheEntry
from marketdesk.providers.base import ProviderError

TTL = timedelta(hours=6)


@dataclass(frozen=True)
class OfficialSeries:
    id: str
    name: str
    unit: str
    show: str  # "level" | "yoy" (index: % change on a year earlier) | "change" (difference on the previous)


SERIES = (
    OfficialSeries("CPIAUCSL", "Consumer prices (CPI-U)", "index 1982–84 = 100", "yoy"),
    OfficialSeries("PCEPILFE", "Core PCE prices", "index 2017 = 100", "yoy"),
    OfficialSeries("UNRATE", "Unemployment rate", "%", "level"),
    OfficialSeries("PAYEMS", "Nonfarm payrolls", "thousands of jobs", "change"),
    OfficialSeries("FEDFUNDS", "Effective federal funds rate", "% a year", "level"),
    OfficialSeries("DGS10", "10-year Treasury yield", "% a year", "level"),
    OfficialSeries("DGS2", "2-year Treasury yield", "% a year", "level"),
    OfficialSeries("T10Y2Y", "10-year minus 2-year Treasury spread", "percentage points", "level"),
    OfficialSeries("GDPC1", "Real GDP", "billions of chained 2017 USD", "yoy"),
    OfficialSeries("UMCSENT", "Consumer sentiment (University of Michigan)", "index 1966:Q1 = 100", "level"),
)
RELEASES = ("Consumer Price Index", "Employment Situation", "Gross Domestic Product", "Personal Income and Outlays",
            "Producer Price Index", "FOMC", "Surveys of Consumers", "Advance Monthly Sales for Retail",
            "Job Openings and Labor Turnover")  # fmt: skip


def _num(v: str | None) -> Decimal | None:
    if v in (None, "", "."):
        return None
    try:
        return Decimal(v)
    except InvalidOperation:
        return None


def summarise(spec: OfficialSeries, meta: dict, obs: list[dict]) -> dict:
    """Latest value, the previous one, the change (or year-on-year % for indices) and the vintage."""
    pts = [(date.fromisoformat(o["date"]), _num(o.get("value")), o.get("realtime_start")) for o in obs]
    pts = [p for p in pts if p[1] is not None]
    base = {"id": spec.id, "name": spec.name, "unit": spec.unit, "show": spec.show,
            "frequency": meta.get("frequency"), "last_updated": meta.get("last_updated"),
            "url": f"https://fred.stlouisfed.org/series/{spec.id}"}  # fmt: skip
    if not pts:
        return {**base, "value": None, "why": "FRED returned no observations."}
    (d, v, vintage), prev = pts[-1], (pts[-2] if len(pts) > 1 else None)
    out = {**base, "date": d.isoformat(), "value": v, "vintage": vintage,
           "previous": {"date": prev[0].isoformat(), "value": prev[1]} if prev else None,
           "change": (v - prev[1]) if prev else None}  # fmt: skip
    if spec.show == "yoy":
        target = d.replace(year=d.year - 1)
        earlier = [p for p in pts if p[0] <= target]
        yo = earlier[-1] if earlier and (target - earlier[-1][0]).days <= 40 else None
        out["yoy_pct"] = ((v / yo[1] - 1) * 100) if yo and yo[1] else None
        if prev:
            target_p = prev[0].replace(year=prev[0].year - 1)
            ep = [p for p in pts if p[0] <= target_p]
            yp = ep[-1] if ep and (target_p - ep[-1][0]).days <= 40 else None
            out["previous_yoy_pct"] = ((prev[1] / yp[1] - 1) * 100) if yp and yp[1] else None
    return out


def upcoming(rows: list[dict], today: date) -> list[dict]:
    """Release dates on or after today for the releases that move markets, one row per release and date."""
    seen, out = set(), []
    for r in rows:
        name = r.get("release_name") or ""
        if not any(k.lower() in name.lower() for k in RELEASES):
            continue
        key = (r.get("release_id"), r.get("date"))
        if key in seen or (r.get("date") or "") < today.isoformat():
            continue
        seen.add(key)
        out.append({"date": r["date"], "release": name, "release_id": r.get("release_id"),
                    "url": f"https://fred.stlouisfed.org/release?rid={r.get('release_id')}"})  # fmt: skip
    return sorted(out, key=lambda x: (x["date"], x["release"]))


def _cache_get(db: Session, key: str):
    row = db.get(MarketCacheEntry, key)
    if row is None:
        return None
    at = row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=UTC)
    return row.payload if datetime.now(UTC) - at < TTL else None


def _cache_put(db: Session, key: str, payload) -> None:
    now = datetime.now(UTC)
    db.merge(
        MarketCacheEntry(key=key, kind="fred", provider="fred", payload=payload, fetched_at=now, last_access_at=now)
    )
    db.commit()


async def official(db: Session, fred, today: date) -> dict:
    base = {
        "source": "FRED, Federal Reserve Bank of St. Louis",
        "attribution": "Source: FRED, Federal Reserve Bank of St. Louis",
    }
    if fred is None or not fred.enabled:
        why = (fred.problem if fred else None) or "FRED is not configured."
        how = ("Create a free account at fred.stlouisfed.org, request an API key (My Account → API Keys) and set "
               "FRED_API_KEY on the server.")  # fmt: skip
        return {**base, "status": "not_configured", "reason": why, "how": how}
    start = (today - timedelta(days=3 * 366)).isoformat()
    rows, failed = [], []
    for spec in SERIES:
        key = f"fred:{spec.id}:{today.isoformat()}"
        cached = await asyncio.to_thread(_cache_get, db, key)
        if cached is None:
            try:
                meta = await asyncio.to_thread(fred.series, spec.id)
                obs = await asyncio.to_thread(fred.observations, spec.id, start)
                cached = {"meta": {k: meta.get(k) for k in ("title", "frequency", "units", "last_updated")}, "obs": obs}
                await asyncio.to_thread(_cache_put, db, key, cached)
            except ProviderError as err:
                failed.append(f"{spec.id}: {err.message}")
                continue
        rows.append(summarise(spec, cached["meta"], cached["obs"]))
    cal_key = f"fred:releases:{today.isoformat()}"
    cal = await asyncio.to_thread(_cache_get, db, cal_key)
    if cal is None:
        try:
            cal = await asyncio.to_thread(
                fred.release_dates, today.isoformat(), (today + timedelta(days=45)).isoformat()
            )
            await asyncio.to_thread(_cache_put, db, cal_key, cal)
        except ProviderError as err:
            failed.append(f"release calendar: {err.message}")
            cal = []
    return {**base, "status": "available" if rows else "unavailable", "series": rows, "calendar": upcoming(cal, today),
            "failed": failed,
            "note": "Values as FRED publishes them; 'vintage' is when the current value became FRED's latest revision. "
                    "Year-on-year changes are computed here from FRED's own observations."}  # fmt: skip
