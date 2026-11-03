"""Listing venues: provider exchange codes mapped to canonical identity (ISO 10383 MIC, country, trading calendar).

Only venues whose codes were checked against Yahoo's own metadata are listed; anything else stays unknown rather than
being guessed from the ticker text. A ticker is not globally unique: INFY.NS (NSE, INR) and INFY (NYSE, USD ADR) are
different listings with different identities, currencies and calendars.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Venue:
    mic: str | None  # None for index "venues" such as S&P's
    country: str
    name: str
    calendar: str | None  # exchange_calendars code used for session states, None if no verified calendar
    timezone: str
    currency: str | None  # trading currency of ordinary listings on this venue (quotes still carry their own)


_IN = dict(country="IN", calendar="XBOM", timezone="Asia/Kolkata", currency="INR")  # NSE and BSE share holidays
_US = dict(country="US", calendar="XNYS", timezone="America/New_York", currency="USD")  # NYSE and Nasdaq share them

# Yahoo exchange codes (search `exchange`, chart metadata `exchangeName`).
YAHOO_VENUES: dict[str, Venue] = {
    "NSI": Venue(mic="XNSE", name="NSE", **_IN),
    "BSE": Venue(mic="XBOM", name="BSE", **_IN),
    "BOM": Venue(mic="XBOM", name="BSE", **_IN),
    "NMS": Venue(mic="XNAS", name="Nasdaq", **_US),
    "NGM": Venue(mic="XNAS", name="Nasdaq", **_US),
    "NCM": Venue(mic="XNAS", name="Nasdaq", **_US),
    "NAS": Venue(mic="XNAS", name="Nasdaq", **_US),
    "NYQ": Venue(mic="XNYS", name="NYSE", **_US),
    "ASE": Venue(mic="XASE", name="NYSE American", **_US),
    "PCX": Venue(mic="ARCX", name="NYSE Arca", **_US),
    "BTS": Venue(mic="BATS", name="Cboe BZX", **_US),
    # US index publishers: no listing venue, US trading calendar.
    "SNP": Venue(mic=None, name="S&P indices", **_US),
    "DJI": Venue(mic=None, name="Dow Jones indices", **_US),
    "NIM": Venue(mic=None, name="Nasdaq indices", **_US),
}
# OTC quotes have no verified session calendar in this app.
YAHOO_VENUES["PNK"] = Venue(
    mic="OTCM", name="OTC Markets", country="US", calendar=None, timezone="America/New_York", currency="USD"
)

# Suffixes Yahoo uses for venues whose code may be missing from a search hit.
_SUFFIX_CODES = {".NS": "NSI", ".BO": "BSE"}

SECURITY_TYPES = {"EQUITY": "EQUITY", "ETF": "ETF", "INDEX": "INDEX", "MUTUALFUND": "FUND"}

# Markets shown with session states, each tied to one calendar.
MARKETS = {
    "IN": {"name": "India (NSE/BSE)", "calendar": "XBOM", "timezone": "Asia/Kolkata"},
    "US": {"name": "US (NYSE/Nasdaq)", "calendar": "XNYS", "timezone": "America/New_York"},
}


def venue_for(exchange_code: str | None, symbol: str | None = None) -> Venue | None:
    if exchange_code and exchange_code.upper() in YAHOO_VENUES:
        return YAHOO_VENUES[exchange_code.upper()]
    if symbol:
        for suffix, code in _SUFFIX_CODES.items():
            if symbol.upper().endswith(suffix):
                return YAHOO_VENUES[code]
    return None


def security_type(raw: str | None) -> str | None:
    if not raw:
        return None
    return SECURITY_TYPES.get(raw.upper(), raw.upper())
