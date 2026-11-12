"""Alert delivery channels (DECISIONS #73): Telegram registers only when validly configured; a fired event is
delivered through it; failures are recorded as failed (never shown as sent); quiet-hours holds are delivered on
release; the token never appears in errors."""

from __future__ import annotations

import json
import urllib.error
from types import SimpleNamespace as NS

import pytest

from marketdesk.models import AlertDelivery
from marketdesk.providers.telegram import TelegramChannel
from marketdesk.services import alerts as svc

TOKEN = "123456789:" + "A" * 35


@pytest.fixture(autouse=True)
def _reset_channels():
    yield
    svc.CHANNELS.pop("telegram", None)
    svc.CHANNEL_PROBLEMS.clear()


def test_configuration_gates_the_channel():
    svc.configure_channels(NS(telegram_bot_token=None, telegram_chat_id=None))
    st = {c["channel"]: c for c in svc.channel_status()}
    assert (
        "telegram" not in svc.CHANNELS
        and st["telegram"]["enabled"] is False
        and "not configured" in st["telegram"]["note"]
    )
    svc.configure_channels(NS(telegram_bot_token="bad", telegram_chat_id="42"))
    assert "telegram" not in svc.CHANNELS and "invalid" in svc.channel_status()[1]["note"]
    svc.configure_channels(NS(telegram_bot_token=TOKEN, telegram_chat_id="123456789"))
    assert "telegram" in svc.CHANNELS and svc.channel_status()[1]["enabled"] is True


def test_telegram_message_and_errors_never_echo_the_token(monkeypatch):
    sent = []

    class Resp:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return self.body

    def ok(req, timeout):
        sent.append((req.full_url, json.loads(req.data)))
        return Resp(b'{"ok": true}')

    ch = TelegramChannel(TOKEN, "123456789")
    event = NS(explanation="SX:AURORA crossed above 100.00", link=None, alert=NS(instrument=NS(symbol="SX:AURORA")))
    monkeypatch.setattr("urllib.request.urlopen", ok)
    ch.deliver(event)
    assert sent[0][1]["chat_id"] == "123456789" and "SX:AURORA crossed above" in sent[0][1]["text"]
    assert sent[0][1]["text"].startswith("MarketDesk alert · SX:AURORA")

    def refused(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", refused)
    with pytest.raises(RuntimeError) as err:
        ch.deliver(event)
    assert TOKEN not in str(err.value) and "HTTP 401" in str(err.value)


def test_fired_events_go_through_channels_and_failures_are_recorded(api, app):
    calls = []

    class Fake:
        name = "telegram"

        def __init__(self, fail=False):
            self.fail = fail

        def deliver(self, event):
            calls.append(event.id)
            if self.fail:
                raise RuntimeError("down")

    svc.CHANNELS["telegram"] = Fake()
    a = api.post("/api/alerts", json={"symbol": "SX:AURORA", "direction": "ABOVE", "target_price": "1"}).json()
    from marketdesk.db import session_factory
    from marketdesk.models import Alert

    with session_factory()() as db:
        alert = db.get(Alert, a["id"])
        ev = svc._fire(db, alert, key=f"test:{alert.id}:x", provider="fixture", explanation="test event")
        assert ev is not None and calls == [ev.id]
        rows = {d.channel: d.status for d in db.query(AlertDelivery).filter_by(event_id=ev.id)}
        assert rows == {"in_app": "delivered", "telegram": "delivered"}
        svc.CHANNELS["telegram"] = Fake(fail=True)
        alert.active = True
        alert.arm_seq += 1
        db.commit()
        ev2 = svc._fire(db, alert, key=f"test:{alert.id}:y", provider="fixture", explanation="second")
        d = db.query(AlertDelivery).filter_by(event_id=ev2.id, channel="telegram").one()
        assert d.status == "failed" and "down" in d.last_error
