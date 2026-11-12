from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from marketdesk.api.deps import market_dep, require_reader, require_writer
from marketdesk.asyncbridge import off_event_loop
from marketdesk.db import get_db
from marketdesk.schemas import AlertEventOut, AlertIn, AlertOut, AlertPatch
from marketdesk.services import alerts as svc
from marketdesk.services.market import MarketDataService

router = APIRouter(prefix="/api", tags=["alerts"])


@router.get("/alerts", response_model=list[AlertOut], dependencies=[Depends(require_reader)])
def list_alerts(db: Session = Depends(get_db)):
    return [svc.alert_dict(a) for a in svc.list_alerts(db)]


@router.post("/alerts", response_model=AlertOut, status_code=201, dependencies=[Depends(require_writer)])
@off_event_loop
async def create(body: AlertIn, db: Session = Depends(get_db), market: MarketDataService = Depends(market_dep)):
    return svc.alert_dict(await svc.create_alert(db, market, body.model_dump()))


@router.patch("/alerts/{aid}", response_model=AlertOut, dependencies=[Depends(require_writer)])
def patch(aid: int, body: AlertPatch, db: Session = Depends(get_db)):
    return svc.alert_dict(svc.update_alert(db, aid, body.model_dump(exclude_unset=True)))


@router.post("/alerts/{aid}/rearm", response_model=AlertOut, dependencies=[Depends(require_writer)])
def rearm(aid: int, db: Session = Depends(get_db)):
    return svc.alert_dict(svc.rearm_alert(db, aid))


@router.delete("/alerts/{aid}", status_code=204, dependencies=[Depends(require_writer)])
def delete(aid: int, db: Session = Depends(get_db)):
    svc.delete_alert(db, aid)
    return Response(status_code=204)


@router.get("/alert-channels", dependencies=[Depends(require_reader)])
def alert_channels() -> dict:
    """Where alert notices are delivered: the in-app inbox always; external channels only when configured."""
    return {"channels": svc.channel_status()}


@router.get("/alert-events", response_model=list[AlertEventOut], dependencies=[Depends(require_reader)])
def events(limit: int = Query(default=50, ge=1, le=200), unread: bool = False, db: Session = Depends(get_db)):
    return svc.list_events(db, limit, unread)


@router.post("/alert-events/read", dependencies=[Depends(require_writer)])
def mark_all_read(db: Session = Depends(get_db)):
    return {"updated": svc.mark_read(db)}


@router.post("/alert-events/{event_id}/read", dependencies=[Depends(require_writer)])
def mark_read(event_id: int, db: Session = Depends(get_db)):
    return {"updated": svc.mark_read(db, event_id)}
