"""Research export (M14): one instrument's research as a Markdown document with source dates and citations.

Public market facts are always included. Private sections — the owner's journal entries and holdings — are included
only when explicitly requested, and the document's header states which private sections it contains. Saved AI
answers are included with their retrieved sources (the questions are the owner's, so they can be left out)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from marketdesk.models import AiAnswer, Instrument, JournalEntry
from marketdesk.services.market import MarketDataService
from marketdesk.services.market_views import actions_payload, fundamentals_payload, snapshot_dict

SECTIONS = ("ai", "journal", "holdings")
PRIVATE = ("journal", "holdings")
DASH = "—"


def _md(text) -> str:
    """Owner/provider text placed in Markdown: one line, no HTML, no table breaks."""
    s = " ".join(str(text or "").split())
    return s.replace("<", "&lt;").replace(">", "&gt;").replace("|", "\\|") or DASH


def _v(x, digits: int = 2) -> str:
    if x is None:
        return DASH
    if isinstance(x, Decimal | float | int) and not isinstance(x, bool):
        return f"{Decimal(str(x)):,.{digits}f}"
    return _md(x)


def _when(meta: dict) -> str:
    bits = [f"source {meta.get('source') or DASH}", f"status {meta.get('status') or DASH}"]
    if meta.get("market_time"):
        bits.append(f"market time {meta['market_time']}")
    if meta.get("fetched_at"):
        bits.append(f"fetched {meta['fetched_at']}")
    return "; ".join(bits)


async def build(
    db: Session, market: MarketDataService, research, inst: Instrument, include: set[str], holdings: list | None
) -> tuple[str, str]:
    now = datetime.now(UTC).replace(microsecond=0)
    private = [s for s in PRIVATE if s in include]
    q = await market.quote(inst.symbol)
    snap = snapshot_dict(inst.symbol, q, inst)
    fund = await fundamentals_payload(market, inst.symbol)
    acts = await actions_payload(market, inst.symbol)
    i = snap["instrument"]
    out = [
        f"# {_md(inst.name or inst.symbol)} ({inst.symbol}) — research notes",
        "",
        f"Exported from MarketDesk on {now.isoformat()} (UTC). Market data are observations from the named source at "
        "the stated times, not live prices. Nothing here is investment advice.",
        "",
        f"**Private sections included:** {', '.join(private) if private else 'none'}.",
        "",
        "## Identity",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Exchange | {_md(i.get('exchange'))} |",
        f"| Currency | {_md(i.get('currency'))} |",
        f"| Country | {_md(i.get('country'))} |",
        f"| Type | {_md(i.get('kind'))} |",
        f"| Time zone | {_md(i.get('timezone'))} |",
        "",
        "## Last observed quote",
        "",
    ]
    qt = snap["quote"]
    if qt:
        out += [
            "| Field | Value |",
            "| --- | --- |",
            f"| Last price | {_v(qt.get('last_price'))} {_md(i.get('currency'))} |",
            f"| Change | {_v(qt.get('change'))} ({_v(qt.get('change_percent'))}%) |",
            f"| Previous close | {_v(qt.get('previous_close'))} |",
            f"| Session date | {_md(qt.get('session_date'))} |",
            "",
        ]
    else:
        out += [f"Not available: {_md(snap['meta'].get('message'))}", ""]
    out += [f"_{_when(snap['meta'])}._", "", "## Fundamentals", ""]
    fv = fund["values"]
    if fv:
        rows = [
            ("Market cap", _v(fv.get("market_cap"), 0), "absolute, " + (fund.get("currency") or DASH)),
            ("P/E", _v(fv.get("pe_ratio")), "ratio"),
            ("Price to book", _v(fv.get("price_to_book")), "ratio"),
            ("Dividend yield", _v(fv.get("dividend_yield_percent")), "percent"),
            ("52-week high", _v(fv.get("fifty_two_week_high")), "price"),
            ("52-week low", _v(fv.get("fifty_two_week_low")), "price"),
            ("Sector", _md(fv.get("sector")), ""),
            ("Industry", _md(fv.get("industry")), ""),
            ("Last fiscal year end", _md(fv.get("last_fiscal_year_end")), "date"),
            ("Most recent quarter", _md(fv.get("most_recent_quarter")), "date"),
        ]
        out += ["| Field | Value | Unit |", "| --- | --- | --- |", *[f"| {a} | {b} | {c} |" for a, b, c in rows], ""]
        out += [f"Note: {_md(n)}" for n in (fv.get("notes") or [])]
    else:
        out += [f"Not available: {_md(fund['meta'].get('message'))}", ""]
    out += [f"_{_when(fund['meta'])}._", "", "## Corporate actions (latest 10)", ""]
    a = acts["actions"][-10:][::-1]
    if a:
        out += ["| Date | Kind | Value |", "| --- | --- | --- |"]
        out += [f"| {x['date']} | {x['kind']} | {_v(x['value'], 4)} |" for x in a]
    else:
        out.append("None reported by the source.")
    out += ["", f"_{_when(acts['meta'])}._", ""]

    if research is not None and inst.country == "US":
        f = research.filings(db, inst, limit=10)
        out += ["## SEC filings (latest 10)", ""]
        if f.get("data"):
            out += ["| Filed | Form | Period | Document |", "| --- | --- | --- | --- |"]
            for r in f["data"]:
                link = f"[{_md(r['description'])}]({r['document_url'] or r['index_url']})"
                out.append(f"| {r['filing_date']} | {r['form']} | {r.get('report_date') or DASH} | {link} |")
            out += ["", f"_Source SEC EDGAR; fetched {f.get('fetched_at') or DASH}._", ""]
        else:
            out += [f"{_md(f.get('status'))}: {_md(f.get('reason'))}", ""]

    if "ai" in include:
        answers = [
            x
            for x in db.scalars(
                select(AiAnswer)
                .where(AiAnswer.status.in_(("done", "reused")), AiAnswer.output.is_not(None))
                .order_by(AiAnswer.created_at.desc())
                .limit(200)
            )
            if inst.symbol in (x.symbols or [])
        ][:5]
        out += ["## Saved AI research (model interpretation of the cited sources)", ""]
        if not answers:
            out += ["No saved answers for this instrument.", ""]
        for ans in answers:
            o = ans.output or {}
            cut = ans.data_cutoff.isoformat() if ans.data_cutoff else DASH
            out += [f"### {_md(o.get('headline') or ans.kind)}", "",
                    f"Task {ans.kind}; model {_md(ans.model)}; data cut-off {cut}.", ""]  # fmt: skip
            for sec in o.get("sections") or []:
                out.append(f"**{_md(sec.get('title'))}**")
                for pt in sec.get("points") or []:
                    refs = "".join(f"[{s}]" for s in pt.get("sources") or [])
                    checks = f" _(check: {'; '.join(pt['checks'])})_" if pt.get("checks") else ""
                    out.append(f"- ({pt.get('kind')}) {_md(pt.get('text'))} {refs}{checks}")
                out.append("")
            srcs = ans.sources or []
            if srcs:
                out.append("Sources retrieved by MarketDesk for this answer:")
                for s in srcs:
                    where = f" <{s['url']}>" if s.get("url") else ""
                    out.append(f"- [{s['id']}] {_md(s.get('title'))}; as of {s.get('as_of') or DASH}; "
                               f"fetched {s.get('fetched_at') or DASH}{where}")  # fmt: skip
                out.append("")

    if "journal" in include:
        entries = list(
            db.scalars(
                select(JournalEntry)
                .where(JournalEntry.instrument_id == inst.id)
                .order_by(JournalEntry.entry_date.desc())
                .limit(20)
            )
        )
        out += ["## Journal (private — the owner's own notes, not recommendations)", ""]
        if not entries:
            out += ["No journal entries for this instrument.", ""]
        for e in entries:
            out += [f"### {e.entry_date} — {_md(e.title)}", ""]
            for label, val in (
                ("Decision", e.decision),
                ("Conviction", e.conviction),
                ("Horizon", e.horizon),
                ("Thesis", e.thesis),
                ("Risks", e.risks),
                ("Invalidation", e.invalidation),
                ("Review date", e.review_date),
            ):
                if val not in (None, ""):
                    out.append(f"- **{label}:** {_md(val)}")
            out.append("")

    if "holdings" in include:
        out += ["## Holding (private — average-cost convention, not a tax report)", ""]
        rows = [h for h in holdings or [] if h["symbol"] == inst.symbol]
        if not rows:
            out += ["Not held.", ""]
        for h in rows:
            out += [
                "| Field | Value |",
                "| --- | --- |",
                f"| Quantity | {_v(h['quantity'], 4)} |",
                f"| Average cost | {_v(h['average_cost'])} |",
                f"| Cost basis | {_v(h['cost_basis'])} |",
                f"| Last price | {_v(h['last_price'])} |",
                f"| Market value | {_v(h['market_value'])} |",
                f"| Unrealized P&L | {_v(h['unrealized_pnl'])} |",
                "",
            ]
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in inst.symbol)
    return f"marketdesk-{safe}-{now.date().isoformat()}.md", "\n".join(out).rstrip() + "\n"
