"""Wire contract for ``/api/me/watchlist``.

camelCase on the wire (matches the frontend domain models); snake_case in Python.

Trust boundary: the PUT body carries ONLY ``symbol`` (membership + order) and an optional
user-authored ``notes``. Instrument/reference metadata (type, underlying, issuer, strike,
ratio, maturity, last trading date) is resolved on the backend from the InstrumentRegistry
/ ``instruments`` table - any such fields a client sends are ignored (``extra="ignore"``).
There is deliberately no owner/user field either.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

InstrumentType = Literal["CW", "STOCK", "INDEX"]

# Hard ceiling independent of settings, purely as a payload-size guard at the edge.
_MAX_ITEMS_HARD = 200


class WatchlistItemInputModel(BaseModel):
    """One item in the PUT body. Only ``symbol`` and ``notes`` are honored."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    symbol: str = Field(min_length=1, max_length=32)
    notes: str | None = Field(default=None, max_length=500)


class WatchlistItemView(BaseModel):
    """One item in a GET / PUT response. Every non-``notes`` field is backend-canonical."""

    model_config = ConfigDict(populate_by_name=True)

    symbol: str
    instrument_type: InstrumentType = Field(serialization_alias="instrumentType")
    underlying_symbol: str | None = Field(default=None, serialization_alias="underlyingSymbol")
    issuer: str | None = None
    strike_price: float | None = Field(default=None, serialization_alias="strikePrice")
    exercise_ratio: float | None = Field(default=None, serialization_alias="exerciseRatio")
    maturity_date: str | None = Field(default=None, serialization_alias="maturityDate")
    last_trading_date: str | None = Field(default=None, serialization_alias="lastTradingDate")
    data_quality: str | None = Field(default=None, serialization_alias="dataQuality")
    metadata_verification: str | None = Field(default=None, serialization_alias="metadataVerification")
    notes: str | None = None


class WatchlistResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[WatchlistItemView]
    updated_at: str | None = Field(default=None, serialization_alias="updatedAt")
    # Lets the client reason about provenance without inferring it.
    source: Literal["server"] = "server"


class WatchlistPutRequest(BaseModel):
    # extra="ignore": a malicious {"owner_id": "..."} or a stale {"strikePrice": 999} is dropped.
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    items: list[WatchlistItemInputModel] = Field(default_factory=list, max_length=_MAX_ITEMS_HARD)
