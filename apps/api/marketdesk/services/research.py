"""Company research data: SEC profile, filings, filing-derived events and normalized statements (US listings).

- SEC data applies to US-registered issuers matched to a CIK through SEC's own ticker file. Other listings (e.g. NSE
  or BSE) get an explicit "not applicable" status; nothing is guessed. An ADR is matched by its own US ticker, so its
  facts are the depositary issuer's SEC filings, never the home listing's.
- Results are cached per company and dataset (submissions 6 h; company facts keyed by the latest periodic filing's
  accession, 24 h). Switching tabs reuses the cache. A failed refresh returns the last good result marked stale.
- `research_checks` records when each dataset was last checked and whether it succeeded, separately from the dates
  of the reported facts ("checked today" is not "new results today").
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from marketdesk.config import Settings
from marketdesk.models import Instrument, InstrumentIdentifier, MarketCacheEntry, ResearchCheck, WatchlistItem
from marketdesk.providers.base import ProviderError
from marketdesk.providers.sec import SecClient, filing_document_url, filing_index_url
from marketdesk.services.financials import compute_ratios, normalize_statements, slim_companyfacts

SOURCE = "SEC EDGAR"
TICKERS_TTL = timedelta(hours=24)
SUBMISSIONS_TTL = timedelta(hours=6)
FACTS_TTL = timedelta(hours=24)
PERIODIC_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A"}
LISTED_FORMS = PERIODIC_FORMS | {"8-K", "8-K/A", "6-K", "DEF 14A", "S-1", "S-1/A", "424B4", "SC 13G", "SC 13D"}
RESULTS_ITEM = "2.02"  # 8-K Item 2.02: Results of Operations and Financial Condition


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, dict):
        return {k: _iso(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_iso(x) for x in v]
    return v


class ResearchService:
    def __init__(self, settings: Settings, client: SecClient | None = None):
        self.settings = settings
        self.client = client or SecClient(settings.sec_user_agent, settings.sec_max_requests_per_second)

    # ------------------------------------------------------------------ cache + checks
    def _cache_get(self, db: Session, key: str):
        row = db.get(MarketCacheEntry, key)
        return (row.payload, row.fetched_at) if row is not None else (None, None)

    def _cache_put(self, db: Session, key: str, kind: str, payload) -> None:
        row = db.get(MarketCacheEntry, key) or MarketCacheEntry(key=key, kind=kind, provider="sec")
        row.payload, row.fetched_at, row.last_access_at = payload, _now(), _now()
        db.merge(row)
        db.commit()

    def _drop_old_facts(self, db: Session, cik: int, keep: str) -> None:
        old = db.scalars(
            select(MarketCacheEntry).where(
                MarketCacheEntry.kind == "sec_companyfacts",
                MarketCacheEntry.key.like(f"sec:facts:%{cik}:%"),
                MarketCacheEntry.key != keep,
            )
        ).all()
        for row in old:
            if row.key.split(":")[-2] == str(cik):  # exactly this company, not a CIK that merely contains it
                db.delete(row)
        if old:
            db.commit()

    def _check(self, db: Session, inst: Instrument, dataset: str, cik: int | None, error: str | None, latest=None):
        row = db.scalar(
            select(ResearchCheck).where(ResearchCheck.instrument_id == inst.id, ResearchCheck.dataset == dataset)
        )
        if row is None:
            row = ResearchCheck(instrument_id=inst.id, dataset=dataset)
            db.add(row)
        row.source_id = str(cik) if cik else None
        row.last_checked_at = _now()
        row.last_error = error[:200] if error else None
        if not error:
            row.last_success_at = row.last_checked_at
            if latest:
                row.latest_filing_date, row.latest_accession = latest
        db.commit()
        return row

    def _cached(self, db, key, kind, ttl, fetch):
        """Fresh cache, else fetch; on failure the last good payload is returned as stale."""
        payload, fetched_at = self._cache_get(db, key)
        if payload is not None and fetched_at and _now() - fetched_at < ttl:
            return payload, fetched_at, "cached", None
        try:
            fresh = fetch()
        except ProviderError as err:
            if payload is not None:
                return payload, fetched_at, "stale", err.message
            raise
        self._cache_put(db, key, kind, fresh)
        return fresh, _now(), "available", None

    # ------------------------------------------------------------------ identity
    def cik_for(self, db: Session, inst: Instrument) -> int:
        if inst.country != "US":
            raise ProviderError(
                "unsupported",
                "SEC filings cover US-registered issuers; this is not a US listing, so SEC data does not apply.",
            )
        existing = db.scalar(
            select(InstrumentIdentifier).where(
                InstrumentIdentifier.instrument_id == inst.id, InstrumentIdentifier.scheme == "cik"
            )
        )
        if existing is not None:
            return int(existing.value)
        tickers, _, _, _ = self._cached(
            db,
            "sec:tickers",
            "sec_tickers",
            TICKERS_TTL,
            lambda: {k: list(v) for k, v in self.client.ticker_map().items()},
        )
        hit = tickers.get(inst.symbol.upper())
        if hit is None:
            raise ProviderError("missing", f"SEC's ticker file has no registrant for {inst.symbol}.")
        cik = int(hit[0])
        db.add(
            InstrumentIdentifier(
                instrument_id=inst.id,
                scheme="cik",
                value=str(cik),
                source="SEC company_tickers.json",
                verified_at=_now(),
            )
        )
        db.commit()
        return cik

    # ------------------------------------------------------------------ datasets
    def _submissions(self, db: Session, inst: Instrument, cik: int):
        try:
            data, fetched, status, note = self._cached(
                db, f"sec:sub:{cik}", "sec_submissions", SUBMISSIONS_TTL, lambda: self.client.submissions(cik)
            )
        except ProviderError as err:
            self._check(db, inst, "sec_submissions", cik, err.message)
            raise
        latest = _latest_periodic(data)
        self._check(db, inst, "sec_submissions", cik, note, latest)
        return data, fetched, status, note

    def envelope(self, db: Session, inst: Instrument, build) -> dict:
        """Common shape: status, reason, source, check times and the dataset-specific data."""
        base = {"symbol": inst.symbol, "source": SOURCE}
        if inst.country != "US":
            return {
                **base,
                "status": "not_applicable",
                "reason": "SEC filings cover US-registered issuers; this is not a US listing, so SEC data does not apply.",  # noqa: E501
                "data": None,
            }
        if not self.client.enabled:
            return {**base, "status": "not_configured", "reason": self.client.problem, "data": None}
        try:
            cik = self.cik_for(db, inst)
            data, meta = build(cik)
        except ProviderError as err:
            status = (
                "not_applicable"
                if err.kind in ("unsupported",)
                else ("missing" if err.kind == "missing" else "unavailable")
            )
            return {**base, "status": status, "reason": err.message, "data": None}
        checks = {
            r.dataset: {
                "last_checked_at": r.last_checked_at,
                "last_success_at": r.last_success_at,
                "last_error": r.last_error,
            }
            for r in db.scalars(select(ResearchCheck).where(ResearchCheck.instrument_id == inst.id))
        }
        return _iso({**base, "cik": cik, **meta, "checks": checks, "data": data})

    def profile(self, db: Session, inst: Instrument) -> dict:
        def build(cik):
            sub, fetched, status, note = self._submissions(db, inst, cik)
            data = {
                "name": sub.get("name"),
                "sic": sub.get("sic"),
                "industry": sub.get("sicDescription"),
                "fiscal_year_end": sub.get("fiscalYearEnd"),
                "state_of_incorporation": sub.get("stateOfIncorporation"),
                "tickers": sub.get("tickers") or [],
                "exchanges": sub.get("exchanges") or [],
                "category": sub.get("category"),
            }
            return data, {"status": status, "fetched_at": fetched, "reason": note}

        return self.envelope(db, inst, build)

    def filings(self, db: Session, inst: Instrument, limit: int = 40) -> dict:
        def build(cik):
            sub, fetched, status, note = self._submissions(db, inst, cik)
            return _filing_rows(sub, cik)[:limit], {"status": status, "fetched_at": fetched, "reason": note}

        return self.envelope(db, inst, build)

    def insider_filings(
        self, db: Session, inst: Instrument, limit: int = 40, forms: tuple[str, ...] = ("4", "4/A")
    ) -> dict:
        """Filings of the given forms (default Form 4 and 4/A) in the issuer's recent submissions, newest first, with
        the raw XML's name. Also used for the structured Schedule 13D/13G beneficial-ownership filings."""

        def build(cik):
            sub, fetched, status, note = self._submissions(db, inst, cik)
            recent = (sub.get("filings") or {}).get("recent") or {}
            rows = []
            for i, form in enumerate(recent.get("form") or []):
                if form not in forms:
                    continue

                def col(name: str, i: int = i):
                    values = recent.get(name) or []
                    return values[i] if i < len(values) else None

                doc = col("primaryDocument") or ""
                accn = col("accessionNumber")
                rows.append(
                    {
                        "form": form,
                        "filing_date": col("filingDate"),
                        "accession": accn,
                        "xml": doc.rsplit("/", 1)[-1] if doc.lower().endswith(".xml") else None,
                        "index_url": filing_index_url(cik, accn) if accn else None,
                    }
                )
            rows.sort(key=lambda r: r["filing_date"] or "", reverse=True)
            return rows[:limit], {"status": status, "fetched_at": fetched, "reason": note}

        return self.envelope(db, inst, build)

    def events(self, db: Session, inst: Instrument) -> dict:
        def build(cik):
            sub, fetched, status, note = self._submissions(db, inst, cik)
            out = []
            for f in _filing_rows(sub, cik):
                if f["form"] in ("8-K", "8-K/A") and RESULTS_ITEM in f["items"]:
                    out.append({**f, "event": "Results announced (8-K Item 2.02)", "certainty": "confirmed"})
                elif f["form"] in PERIODIC_FORMS:
                    out.append({**f, "event": f"Periodic report filed ({f['form']})", "certainty": "confirmed"})
            return out[:30], {"status": status, "fetched_at": fetched, "reason": note}

        return self.envelope(db, inst, build)

    def financials(
        self, db: Session, inst: Instrument, period: str, price=None, price_date=None, price_ccy=None, max_periods=None
    ):
        def build(cik):
            sub, _, _, _ = self._submissions(db, inst, cik)
            latest = _latest_periodic(sub)
            # A new periodic filing invalidates the cache; "v2": slimmed payloads (financials.slim_companyfacts).
            key = f"sec:facts:v2:{cik}:{latest[1] if latest else 'none'}"
            try:
                facts, fetched, status, note = self._cached(
                    db, key, "sec_companyfacts", FACTS_TTL, lambda: slim_companyfacts(self.client.companyfacts(cik))
                )
            except ProviderError as err:
                self._check(db, inst, "sec_companyfacts", cik, err.message)
                raise
            self._check(db, inst, "sec_companyfacts", cik, note, latest)
            if status == "available":  # a fresh copy: earlier ones (older filings, unslimmed format) are dead weight
                self._drop_old_facts(db, cik, key)
            try:
                n = max_periods or (5 if period == "annual" else 8)
                st = normalize_statements(facts, sub.get("sic"), period, n)
            except ValueError as exc:
                raise ProviderError("malformed", f"SEC company facts could not be normalized: {exc}") from exc
            st["ratios"] = compute_ratios(st, price, price_date, price_ccy)
            st["coverage_note"] = _coverage_note(st, _filing_rows(sub, cik), period)
            st["entity"] = facts.get("entityName")
            st["facts_url"] = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
            for line in st["lines"]:
                for v in line["values"]:
                    v["source_url"] = filing_index_url(cik, v["accession"])
            for r in st["ratios"]:
                for i in r.get("inputs") or []:
                    if i:
                        i["source_url"] = filing_index_url(cik, i["accession"])
            return st, {"status": status, "fetched_at": fetched, "reason": note}

        return self.envelope(db, inst, build)

    # ------------------------------------------------------------------ scheduled refresh (worker)
    def refresh_tracked(self, db: Session, limit: int = 20) -> dict:
        """Daily check of watchlisted US listings: submissions, and company facts only after a new periodic filing."""
        if not self.client.enabled:
            return {"skipped": "SEC not configured"}
        due = _now() - timedelta(hours=self.settings.research_refresh_hours)
        insts = list(
            db.scalars(
                select(Instrument)
                .join(WatchlistItem, WatchlistItem.instrument_id == Instrument.id)
                .where(Instrument.country == "US")
                .distinct()
            )
        )
        checked = refreshed = errors = 0
        for inst in insts[:limit]:
            check = db.scalar(
                select(ResearchCheck).where(
                    ResearchCheck.instrument_id == inst.id, ResearchCheck.dataset == "sec_submissions"
                )
            )
            if check and check.last_checked_at and check.last_checked_at > due:
                continue
            try:
                cik = self.cik_for(db, inst)
                db.query(MarketCacheEntry).filter(MarketCacheEntry.key == f"sec:sub:{cik}").delete()
                db.commit()
                before = check.latest_accession if check else None
                sub, _, _, _ = self._submissions(db, inst, cik)
                checked += 1
                latest = _latest_periodic(sub)
                if latest and latest[1] != before:
                    self.financials(db, inst, "annual")
                    refreshed += 1
            except ProviderError:
                errors += 1
        return {"checked": checked, "facts_refreshed": refreshed, "errors": errors}


def _filing_rows(sub: dict, cik: int) -> list[dict]:
    recent = (sub.get("filings") or {}).get("recent") or {}
    n = len(recent.get("accessionNumber") or [])

    def col(name: str, i: int):
        values = recent.get(name) or []
        return values[i] if i < len(values) else None

    rows = []
    for i in range(n):
        form, accn = col("form", i), col("accessionNumber", i)
        if not form or not accn or form not in LISTED_FORMS:
            continue
        doc = col("primaryDocument", i)
        rows.append(
            {
                "form": form,
                "filing_date": col("filingDate", i),
                "report_date": col("reportDate", i) or None,
                "accession": accn,
                "description": col("primaryDocDescription", i) or form,
                "items": [x.strip() for x in str(col("items", i) or "").split(",") if x.strip()],
                "document_url": filing_document_url(cik, accn, doc) if doc else None,
                "index_url": filing_index_url(cik, accn),
            }
        )
    rows.sort(key=lambda r: r["filing_date"] or "", reverse=True)
    return rows


ANNUAL_REPORTS = {"10-K", "20-F", "40-F"}


def _fmt_day(d) -> str:
    d = d if isinstance(d, date) else date.fromisoformat(str(d))
    return f"{d.day} {d:%b %Y}"


def _coverage_note(st: dict, rows: list[dict], period: str) -> str | None:
    """Say so when the newest periodic report is not yet in SEC's company-facts data (the figures are then older than
    the filing list suggests). Amendments are ignored: they often carry no financial statements."""
    wanted = ANNUAL_REPORTS if period == "annual" else ANNUAL_REPORTS | {"10-Q"}
    latest = next((r for r in rows if r["form"] in wanted and r["filing_date"]), None)
    values = [v for line in st["lines"] for v in line["values"]]
    if latest is None or not values or any(v["accession"] == latest["accession"] for v in values):
        return None
    newest = max(values, key=lambda v: v["filed"])
    return (
        f"The latest {latest['form']} (filed {_fmt_day(latest['filing_date'])}, accession {latest['accession']}) "
        "has no figures in SEC's company-facts data yet, so it is not reflected here. The newest figures shown come "
        f"from the {newest['form']} filed {_fmt_day(newest['filed'])}."
    )


def _latest_periodic(sub: dict):
    rows = [r for r in _filing_rows(sub, 0) if r["form"] in PERIODIC_FORMS and r["filing_date"]]
    if not rows:
        return None
    top = rows[0]
    return date.fromisoformat(top["filing_date"]), top["accession"]
