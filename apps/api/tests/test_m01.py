# ruff: noqa: E501
"""M01 India + US: listing identity, disambiguated search with region filter, exchange session states (DST,
holidays, early closes, special sessions, calendar bounds), normalized comparison, migration of a populated
database and restore of a pre-M01 backup."""

from __future__ import annotations

import json
import types
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from marketdesk.api.app import create_app
from marketdesk.config import normalize_database_url
from marketdesk.db import get_engine, session_factory
from marketdesk.db.migrations import upgrade
from marketdesk.providers.venues import security_type, venue_for
from marketdesk.providers.yahoo import YahooProvider, instrument_from_meta
from marketdesk.services.backup import checksum
from marketdesk.services.compare import align_and_rebase
from marketdesk.services.market import MarketDataService
from marketdesk.services.sessions import session_state

from .conftest import PG_URL, Api, _reset_postgres, make_settings, migrated


# --------------------------------------------------------------------------- identity
def test_venues_map_provider_codes_not_ticker_text():
    assert (venue_for("NSI").mic, venue_for("NSI").country) == ("XNSE", "IN")
    assert (venue_for("NMS").mic, venue_for("NYQ").mic, venue_for("PCX").mic) == ("XNAS", "XNYS", "ARCX")
    assert venue_for(None, "TCS.NS").mic == "XNSE" and venue_for(None, "TCS.BO").mic == "XBOM"
    assert venue_for("ZZZ", "WEIRD") is None  # unknown stays unknown
    assert venue_for("PNK").calendar is None  # OTC: no verified calendar
    assert security_type("MUTUALFUND") == "FUND" and security_type("ETF") == "ETF"


def test_quote_metadata_gives_listing_identity():
    nse = instrument_from_meta(
        "INFY.NS",
        {
            "exchangeName": "NSI",
            "fullExchangeName": "NSE",
            "currency": "INR",
            "exchangeTimezoneName": "Asia/Kolkata",
            "instrumentType": "EQUITY",
            "longName": "Infosys Limited",
        },
    )
    adr = instrument_from_meta(
        "INFY",
        {
            "exchangeName": "NYQ",
            "fullExchangeName": "NYSE",
            "currency": "USD",
            "exchangeTimezoneName": "America/New_York",
            "instrumentType": "EQUITY",
            "longName": "Infosys Limited",
        },
    )
    index = instrument_from_meta("^NSEI", {"exchangeName": "NSI", "currency": "INR", "instrumentType": "INDEX"})
    assert (nse.mic, nse.country, nse.currency) == ("XNSE", "IN", "INR")
    assert (adr.mic, adr.country, adr.currency) == ("XNYS", "US", "USD")  # same name, different listing
    assert (index.mic, index.country, index.kind) == (None, "IN", "INDEX")


class _Search:
    def __init__(self, *a, **k):
        self.quotes = [
            {
                "symbol": "INFY.NS",
                "longname": "Infosys Limited",
                "exchange": "NSI",
                "exchDisp": "NSE",
                "quoteType": "EQUITY",
            },
            {
                "symbol": "INFY",
                "longname": "Infosys Limited",
                "exchange": "NYQ",
                "exchDisp": "NYSE",
                "quoteType": "EQUITY",
            },
            {
                "symbol": "INFY.BO",
                "longname": "Infosys Limited",
                "exchange": "BSE",
                "exchDisp": "Bombay",
                "quoteType": "EQUITY",
            },
            {
                "symbol": "QQQ",
                "longname": "Invesco QQQ Trust",
                "exchange": "NMS",
                "exchDisp": "NASDAQ",
                "quoteType": "ETF",
            },
        ]


def test_search_disambiguates_listings_and_filters_by_region(tmp_path):
    s = migrated(make_settings(tmp_path, marketdesk_env="development", dev_auth_bypass=True, data_provider="yahoo"))
    yp = YahooProvider(timeout=1)
    yp._yf = types.SimpleNamespace(Search=_Search, Ticker=None)
    app = create_app(s, market=MarketDataService(yp, s, None))
    with TestClient(app) as c:
        allr = c.get("/api/market/search", params={"q": "infosys"}).json()["results"]
        assert [(r["symbol"], r["mic"], r["country"]) for r in allr[:3]] == [
            ("INFY.NS", "XNSE", "IN"),
            ("INFY", "XNYS", "US"),
            ("INFY.BO", "XBOM", "IN"),
        ]
        us = c.get("/api/market/search", params={"q": "infosys", "region": "US"}).json()["results"]
        assert [r["symbol"] for r in us] == ["INFY", "QQQ"] and us[1]["kind"] == "ETF"
        india = c.get("/api/market/search", params={"q": "infosys", "region": "IN"}).json()["results"]
        assert [r["symbol"] for r in india] == ["INFY.NS", "INFY.BO"]
        assert all(r["identity_verified"] is False for r in allr)  # a search hit is not a verified listing


# --------------------------------------------------------------------------- sessions
@pytest.mark.parametrize(
    ("code", "at", "state", "reason"),
    [
        ("XNYS", datetime(2026, 3, 6, 14, 0, tzinfo=UTC), "closed", "Before the open."),  # 09:00 EST
        ("XNYS", datetime(2026, 3, 9, 13, 45, tzinfo=UTC), "open", "Regular session."),  # 09:45 EDT after DST
        ("XNYS", datetime(2026, 11, 2, 14, 15, tzinfo=UTC), "closed", "Before the open."),  # 09:15 EST after DST ends
        ("XNYS", datetime(2026, 11, 26, 15, 0, tzinfo=UTC), "closed", "Exchange holiday."),  # Thanksgiving
        ("XNYS", datetime(2026, 11, 27, 17, 0, tzinfo=UTC), "open", "Early close today."),
        ("XNYS", datetime(2026, 11, 27, 18, 30, tzinfo=UTC), "closed", "After the close."),
        ("XNYS", datetime(2026, 11, 7, 15, 0, tzinfo=UTC), "closed", "Weekend."),
        ("XBOM", datetime(2026, 1, 26, 5, 0, tzinfo=UTC), "closed", "Exchange holiday."),  # Republic Day
        ("XBOM", datetime(2026, 11, 3, 5, 0, tzinfo=UTC), "open", "Regular session."),  # 10:30 IST
        ("XBOM", datetime(2026, 11, 3, 3, 30, tzinfo=UTC), "closed", "Before the open."),  # 09:00 IST
    ],
)
def test_session_states_follow_the_published_calendar(code, at, state, reason):
    s = session_state(code, at)
    assert (s["state"], s["reason"]) == (state, reason)


def test_unknown_states_are_never_guessed():
    assert session_state("XBOM", datetime(2026, 11, 8, 12, 0, tzinfo=UTC))["state"] == "unknown"  # Muhurat Sunday
    beyond = session_state("XBOM", datetime(2027, 2, 1, 5, 0, tzinfo=UTC))
    assert beyond["state"] == "unknown" and "Outside the calendar" in beyond["reason"]
    assert session_state(None)["state"] == "unknown"


def test_sessions_endpoint(api):
    rows = api.get("/api/market/sessions").json()
    assert {r["market"] for r in rows} == {"IN", "US"}
    assert all(
        r["state"] in ("open", "closed", "unknown") and r["source"].startswith("exchange_calendars") for r in rows
    )


# --------------------------------------------------------------------------- comparison
def test_alignment_keeps_only_common_trading_dates_and_rebases_to_100():
    d = date
    india = [(d(2026, 1, 23), Decimal("100")), (d(2026, 1, 26), Decimal("101")), (d(2026, 1, 27), Decimal("110"))]
    us = [
        (d(2026, 1, 16), Decimal("50")),
        (d(2026, 1, 19), Decimal("51")),
        (d(2026, 1, 23), Decimal("40")),
        (d(2026, 1, 26), Decimal("44")),
        (d(2026, 1, 27), Decimal("42")),
    ]
    india = [p for p in india if p[0] != d(2026, 1, 26)]  # Republic Day: no Indian bar
    out = align_and_rebase({"IN": india, "US": us})
    assert out["dates"] == [d(2026, 1, 23), d(2026, 1, 27)] and out["base_date"] == d(2026, 1, 23)
    assert out["values"]["IN"] == [Decimal("100.00"), Decimal("110.00")]
    assert out["values"]["US"] == [Decimal("100.00"), Decimal("105.00")]
    assert out["excluded"] == {"IN": 0, "US": 3}
    assert align_and_rebase({"A": india[:1], "B": us})["dates"] == []  # fewer than two common dates


def test_compare_endpoint_limits_and_labels(api):
    assert api.get("/api/market/compare", params={"symbols": "SX:AURORA"}).status_code == 422
    four = "SX:AURORA,SX:BANYAN,SX:CORVID,SX:DELTA"
    assert api.get("/api/market/compare", params={"symbols": four}).status_code == 422
    r = api.get("/api/market/compare", params={"symbols": "SX:AURORA,SX:BANYAN", "range": "1M"}).json()
    assert r["complete"] and Decimal(r["series"]["SX:AURORA"][0]) == 100 and "dividends are not included" in r["method"]
    assert len(r["dates"]) == len(r["series"]["SX:BANYAN"])


# --------------------------------------------------------------------------- migration of a populated database
_ROWS_0001 = [
    "INSERT INTO instruments (id, provider, symbol, name, exchange, currency, timezone, kind, created_at, updated_at) VALUES "
    "(1,'yahoo','RELIANCE.NS','Reliance Industries Limited','NSE','INR','Asia/Kolkata','EQUITY','2026-11-01 10:00:00','2026-11-01 10:00:00'),"
    "(2,'yahoo','AAPL','Apple Inc.','NasdaqGS','USD','America/New_York','EQUITY','2026-11-01 10:00:00','2026-11-01 10:00:00'),"
    "(3,'yahoo','^NSEI','NIFTY 50','NSE','INR','Asia/Kolkata','INDEX','2026-11-01 10:00:00','2026-11-01 10:00:00'),"
    "(4,'yahoo','SMR','NuScale Power Corporation','NYSE','USD','America/New_York','EQUITY','2026-11-01 10:00:00','2026-11-01 10:00:00'),"
    "(5,'yahoo','ODD',NULL,'Somewhere',NULL,NULL,NULL,'2026-11-01 10:00:00','2026-11-01 10:00:00')",
    "INSERT INTO watchlists (id, name, position, sort_key, sort_dir, created_at, updated_at) VALUES "
    "(1,'Harsh Stocks',0,'manual','asc','2026-11-01 10:00:00','2026-11-01 10:00:00')",
    "INSERT INTO watchlist_items (id, watchlist_id, instrument_id, position, added_at) VALUES "
    "(1,1,4,0,'2026-11-01 10:00:00'),(2,1,1,1,'2026-11-01 10:00:00'),(3,1,2,2,'2026-11-01 10:00:00')",
]


def _dump(conn, table, cols):
    return [tuple(r) for r in conn.execute(text(f"SELECT {', '.join(cols)} FROM {table} ORDER BY id"))]


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_migration_0002_preserves_existing_rows_and_adds_identity(tmp_path, backend):
    if backend == "postgres":
        if not PG_URL:
            pytest.skip("needs TEST_DATABASE_URL")
        _reset_postgres(PG_URL)
        url = normalize_database_url(PG_URL)
    else:
        url = f"sqlite:///{tmp_path}/m.db"
    upgrade(url, "0001")
    engine = create_engine(url)
    inst_cols = ["id", "provider", "symbol", "name", "exchange", "currency", "timezone", "kind", "created_at"]
    with engine.begin() as conn:
        for stmt in _ROWS_0001:
            conn.execute(text(stmt))
    with engine.connect() as conn:
        before = (
            _dump(conn, "instruments", inst_cols),
            _dump(conn, "watchlist_items", ["id", "watchlist_id", "instrument_id", "position"]),
        )
    upgrade(url, "head")
    with engine.connect() as conn:
        after = (
            _dump(conn, "instruments", inst_cols),
            _dump(conn, "watchlist_items", ["id", "watchlist_id", "instrument_id", "position"]),
        )
        identity = {
            r[0]: r[1:]
            for r in conn.execute(text("SELECT symbol, mic, country, identity_verified_at FROM instruments"))
        }
        idents = {
            r[0]: r[1]
            for r in conn.execute(
                text("SELECT instrument_id, value FROM instrument_identifiers WHERE scheme = 'yahoo'")
            )
        }
    engine.dispose()
    assert after == before  # every pre-existing value and the saved list are unchanged
    assert identity["RELIANCE.NS"][:2] == ("XNSE", "IN") and identity["AAPL"][:2] == ("XNAS", "US")
    assert identity["SMR"][:2] == ("XNYS", "US") and identity["^NSEI"][:2] == (None, "IN")
    assert identity["ODD"][:2] == (None, None)  # not guessed
    assert all(v[2] is None for v in identity.values())  # derived, so not yet marked verified
    assert idents == {1: "RELIANCE.NS", 2: "AAPL", 3: "^NSEI", 4: "SMR", 5: "ODD"}


def test_pre_m01_backup_restores_into_the_current_schema(tmp_path):
    from marketdesk.cli import restore_with_migrations

    s = migrated(make_settings(tmp_path / "src", marketdesk_env="development", dev_auth_bypass=True))
    with TestClient(create_app(s)) as c:
        api = Api(c)
        api.refresh_csrf()
        wid = api.post("/api/watchlists", json={"name": "Keep"}).json()["id"]
        assert api.post(f"/api/watchlists/{wid}/items", json={"symbol": "SX:AURORA"}).status_code == 201
        api.post(
            "/api/portfolio/transactions", json={"type": "DEPOSIT", "effective_date": "2026-01-02", "amount": "500.25"}
        )
        data = api.get("/api/backup/export").json()
    # Rewrite it as the previous version (schema 0001) would have produced it.
    old = json.loads(json.dumps(data))
    old["schema_revision"] = "0001"
    old["tables"].pop("instrument_identifiers")
    inst = old["tables"]["instruments"]
    keep = [
        i
        for i, col in enumerate(inst["columns"])
        if col not in ("exchange_code", "mic", "country", "identity_source", "identity_verified_at")
    ]
    inst["columns"] = [inst["columns"][i] for i in keep]
    inst["rows"] = [[row[i] for i in keep] for row in inst["rows"]]
    old["counts"] = {k: len(v["rows"]) for k, v in old["tables"].items()}
    old["checksum"] = checksum(old["tables"])

    target = make_settings(
        tmp_path / "dst",
        marketdesk_env="development",
        dev_auth_bypass=True,
        database_url=f"sqlite:///{tmp_path}/restored.db",
    )
    app = create_app(target)
    restore_with_migrations(target.effective_database_url, get_engine(), old)
    with TestClient(app) as c:
        api = Api(c)
        lists = api.get("/api/watchlists").json()
        assert [(w["name"], [i["symbol"] for i in w["items"]]) for w in lists] == [("Keep", ["SX:AURORA"])]
        assert api.get("/api/portfolio/summary").json()["cash"] == "500.25"
    with session_factory()() as db:
        assert db.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0002"
        assert db.execute(text("SELECT count(*) FROM instrument_identifiers")).scalar() == 1  # backfilled
