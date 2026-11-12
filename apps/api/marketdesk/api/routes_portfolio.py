from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader, require_writer, settings_dep
from marketdesk.api.errors import AppError
from marketdesk.asyncbridge import off_event_loop
from marketdesk.config import Settings
from marketdesk.db import get_db
from marketdesk.models import LedgerTransaction
from marketdesk.schemas import (
    ImportCommitOut,
    ImportPreviewOut,
    PortfolioOverviewOut,
    PortfolioSummaryOut,
    TransactionIn,
    TransactionOut,
    TransactionPage,
)
from marketdesk.services import broker_csv, csv_io
from marketdesk.services import portfolio as svc
from marketdesk.services.market import MarketDataService

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])
CSV_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel", "text/plain", "application/octet-stream", ""}


def _with_state(db: Session, t: LedgerTransaction) -> dict:
    states, _ = svc.current_states(db)
    return svc.txn_dict(t, states)


Account = Query(default="INR", pattern="^(INR|USD)$", description="Currency account")


@router.get("/summary", response_model=PortfolioSummaryOut, dependencies=[Depends(require_reader)])
@off_event_loop
async def summary(
    currency: str = Account, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)
):
    return await svc.portfolio_summary(db, market, currency)


@router.get("/overview", response_model=PortfolioOverviewOut, dependencies=[Depends(require_reader)])
@off_event_loop
async def overview(db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    """All accounts in their own currency, plus a display-only conversion to INR at the current valuation rate."""
    return await svc.portfolio_overview(db, market, "INR")


@router.get("/transactions", response_model=TransactionPage, dependencies=[Depends(require_reader)])
def transactions(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    symbol: str | None = Query(default=None, max_length=32),
    type: str | None = Query(default=None, pattern="^(DEPOSIT|WITHDRAWAL|BUY|SELL|DIVIDEND|SPLIT|FX)$"),  # noqa: A002
    currency: str | None = Query(default=None, pattern="^(INR|USD)$"),
    db: Session = Depends(get_db),
):
    return svc.list_transactions(db, limit, offset, symbol.upper() if symbol else None, type, currency)


@router.post("/transactions", response_model=TransactionOut, status_code=201, dependencies=[Depends(require_writer)])
@off_event_loop
async def create(body: TransactionIn, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    t = await svc.create_transaction(db, market, body.model_dump())
    return _with_state(db, t)


@router.put("/transactions/{tid}", response_model=TransactionOut, dependencies=[Depends(require_writer)])
@off_event_loop
async def update(
    tid: int, body: TransactionIn, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)
):
    t = await svc.update_transaction(db, market, tid, body.model_dump())
    return _with_state(db, t)


@router.delete("/transactions/{tid}", status_code=204, dependencies=[Depends(require_writer)])
def delete(tid: int, db: Session = Depends(get_db)):
    svc.delete_transaction(db, tid)
    return Response(status_code=204)


@router.post("/import/preview", response_model=ImportPreviewOut, dependencies=[Depends(require_writer)])
@off_event_loop
async def import_preview(
    file: UploadFile = File(...),
    mapping: str | None = Query(default=None, max_length=64, description="Broker mapping id; omit for canonical"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    market: MarketDataService = Depends(market_dep),
):
    name = (file.filename or "").lower()
    if not name.endswith(".csv") or (file.content_type or "") not in CSV_TYPES:
        raise AppError(415, "unsupported_media_type", "Upload a .csv file.")
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise AppError(413, "payload_too_large", f"CSV files are limited to {settings.max_upload_bytes // 1000} KB.")
    notes: list[str] = []
    if mapping:
        m = broker_csv.get_mapping(db, mapping)
        content, notes = broker_csv.convert(content, m)
    out = await csv_io.build_preview(db, settings, market, file.filename, content)
    return {**out, "conversion_notes": notes, "mapping": mapping}


@router.get("/csv-mappings", dependencies=[Depends(require_reader)])
def csv_mappings(db: Session = Depends(get_db)) -> dict:
    """Broker CSV presets (built-in) and the owner's saved column mappings."""
    return {"mappings": broker_csv.all_mappings(db), "fields": list(broker_csv.FIELDS),
            "required": list(broker_csv.REQUIRED_FIELDS), "date_formats": list(broker_csv.DATE_FORMATS)}  # fmt: skip


@router.post("/csv-mappings", status_code=201, dependencies=[Depends(require_writer)])
def save_csv_mapping(body: dict, db: Session = Depends(get_db)) -> dict:
    return broker_csv.save_mapping(db, body)


@router.delete("/csv-mappings/{mid}", status_code=204, dependencies=[Depends(require_writer)])
def delete_csv_mapping(mid: str, db: Session = Depends(get_db)) -> Response:
    broker_csv.delete_mapping(db, mid)
    return Response(status_code=204)


@router.post("/import/{token}/commit", response_model=ImportCommitOut, dependencies=[Depends(require_writer)])
@off_event_loop
async def import_commit(token: str, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    return await csv_io.commit_import(db, market, token)


def _csv_response(body: str, name: str) -> Response:
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="marketdesk-{name}-{stamp}.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/export/transactions.csv", dependencies=[Depends(require_reader)])
def export_transactions(db: Session = Depends(get_db)):
    return _csv_response(csv_io.export_transactions_csv(db), "transactions")


@router.get("/export/holdings.csv", dependencies=[Depends(require_reader)])
@off_event_loop
async def export_holdings(
    currency: str = Account, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)
):
    summary = await svc.portfolio_summary(db, market, currency)
    return _csv_response(csv_io.export_holdings_csv(summary), f"holdings-{currency.lower()}")
