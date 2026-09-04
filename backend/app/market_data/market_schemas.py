from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field
from datetime import datetime, timezone

class CanonicalQuote(BaseModel):
    symbol: str
    instrument_type: Literal["STOCK", "INDEX", "CW"] = "STOCK"

    # Last matching trade metrics
    last_price: Optional[float] = None
    reference_price: Optional[float] = None
    ceiling_price: Optional[float] = None
    floor_price: Optional[float] = None
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    average_price: Optional[float] = None
    price_change: Optional[float] = None
    price_change_percent: Optional[float] = None
    total_volume: Optional[int] = None
    trading_value: Optional[float] = None
    traded_quantity: Optional[int] = None

    # Top-of-Book & Depth
    bid1_price: Optional[float] = None
    bid1_quantity: Optional[int] = None
    ask1_price: Optional[float] = None
    ask1_quantity: Optional[int] = None

    bid2_price: Optional[float] = None
    bid2_quantity: Optional[int] = None
    ask2_price: Optional[float] = None
    ask2_quantity: Optional[int] = None

    bid3_price: Optional[float] = None
    bid3_quantity: Optional[int] = None
    ask3_price: Optional[float] = None
    ask3_quantity: Optional[int] = None

    # Warrant specific fields
    underlying_symbol: Optional[str] = None
    underlying_price: Optional[float] = None
    strike_price: Optional[float] = None
    exercise_ratio: Optional[float] = None
    maturity_date: Optional[str] = None
    last_trading_date: Optional[str] = None
    iv_bid: Optional[float] = None
    iv_trade: Optional[float] = None
    iv_ask: Optional[float] = None

    # Timestamps
    provider_trading_date: Optional[str] = None
    provider_timestamp: Optional[str] = None
    source_timestamp: Optional[int] = None  # compatibility alias: latest trade timestamp
    trade_timestamp: Optional[int] = None  # epoch ms, only advanced by a real trade event
    book_timestamp: Optional[int] = None  # epoch ms, only advanced by order-book events
    trade_received_timestamp: Optional[int] = None
    book_received_timestamp: Optional[int] = None
    provider_market_status: Optional[str] = None
    # Session of the most recently accepted trade/book event.  This is separate
    # from reference_session_date because bands can be refreshed before the first
    # live tick of a new day.
    market_session_date: Optional[str] = None
    # Trading-session metadata is refreshed separately from the live trade/book stream.
    # Keeping its own session and observation timestamp prevents a reference-only quote
    # from being mistaken for a fresh trade while still allowing Redis warm restores.
    reference_session_date: Optional[str] = None
    reference_timestamp: Optional[int] = None  # epoch ms
    received_timestamp: int = Field(default_factory=lambda: int(datetime.now(timezone.utc).timestamp() * 1000))

    def to_wire_snapshot_row(self, display_eligible: bool = True) -> Dict[str, Any]:
        """
        Converts the canonical quote to the gateway wire format expected by the frontend.
        Note: The frontend normalizeTransportPriceToRawVnd multiplies by 1000 for transport price fields.
        For index (POINTS) or raw VND, we format accordingly:
        - For stocks & CWs: divide raw VND by 1000 so frontend x1000 yields exact raw VND.
        - For Index: points remain unchanged or formatted for frontend transport.
        
        If display_eligible is False (e.g. during market lunch break or outside active sessions),
        realtime-dependent trade and depth fields are set to None (rendering as —),
        while reference and static contract terms remain visible.
        """
        is_index = self.instrument_type == "INDEX"
        scale = 1.0 if is_index else 1000.0

        def to_wire_prc(val: Optional[float]) -> Optional[float]:
            if val is None:
                return None
            return round(val / scale, 6)

        def to_wire_iv(val: Optional[float]) -> Optional[float]:
            if val is None:
                return None
            return round(val * 100.0, 4)

        traded = to_wire_prc(self.last_price) if display_eligible else None
        change = to_wire_prc(self.price_change) if display_eligible else None
        chg_pct = self.price_change_percent if display_eligible else None
        total_vol = self.total_volume if display_eligible else None
        traded_qty = self.traded_quantity if display_eligible else None
        trading_val = to_wire_prc(self.trading_value) if display_eligible else None

        bid1_prc = to_wire_prc(self.bid1_price) if display_eligible else None
        bid1_qty = self.bid1_quantity if display_eligible else None
        ask1_prc = to_wire_prc(self.ask1_price) if display_eligible else None
        ask1_qty = self.ask1_quantity if display_eligible else None

        bid2_prc = to_wire_prc(self.bid2_price) if display_eligible else None
        bid2_qty = self.bid2_quantity if display_eligible else None
        ask2_prc = to_wire_prc(self.ask2_price) if display_eligible else None
        ask2_qty = self.ask2_quantity if display_eligible else None

        bid3_prc = to_wire_prc(self.bid3_price) if display_eligible else None
        bid3_qty = self.bid3_quantity if display_eligible else None
        ask3_prc = to_wire_prc(self.ask3_price) if display_eligible else None
        ask3_qty = self.ask3_quantity if display_eligible else None

        vol1 = to_wire_iv(self.iv_ask) if display_eligible else None
        vol2 = to_wire_iv(self.iv_trade) if display_eligible else None
        vol3 = to_wire_iv(self.iv_bid) if display_eligible else None

        return {
            "Symbol": self.symbol,
            "Traded": traded,
            "Ref": to_wire_prc(self.reference_price),
            "Ceil": to_wire_prc(self.ceiling_price),
            "Floor": to_wire_prc(self.floor_price),
            "Open_Prc": to_wire_prc(self.open_price) if display_eligible else None,
            "High_Prc": to_wire_prc(self.high_price) if display_eligible else None,
            "Low_Prc": to_wire_prc(self.low_price) if display_eligible else None,
            "Avg_Prc": to_wire_prc(self.average_price) if display_eligible else None,
            "change": change,
            "ChangePercent": chg_pct,
            "Total_Vol": total_vol,
            "Traded_Qty": traded_qty,
            "Trading_Val": trading_val,
            "Bid1_Prc": bid1_prc,
            "Bid1_Qty": bid1_qty,
            "Ask1_Prc": ask1_prc,
            "Ask1_Qty": ask1_qty,
            "Bid2_Prc": bid2_prc,
            "Bid2_Qty": bid2_qty,
            "Ask2_Prc": ask2_prc,
            "Ask2_Qty": ask2_qty,
            "Bid3_Prc": bid3_prc,
            "Bid3_Qty": bid3_qty,
            "Ask3_Prc": ask3_prc,
            "Ask3_Qty": ask3_qty,
            "Under_Prc": to_wire_prc(self.underlying_price),
            "Strike_Prc": to_wire_prc(self.strike_price),
            "Ratio": self.exercise_ratio,
            "Under_Symbol": self.underlying_symbol,
            "Vol1": vol1,
            "Vol2": vol2,
            "Vol3": vol3,
            "LastTradingDate": self.last_trading_date,
            "MaturityDate": self.maturity_date,
            "_ts_source": self.source_timestamp,
            "_ts_trade": self.trade_timestamp,
            "_ts_book": self.book_timestamp,
            "_received_trade": self.trade_received_timestamp,
            "_received_book": self.book_received_timestamp,
            "_market_session_date": self.market_session_date,
            "_ts_reference": self.reference_timestamp,
            "_reference_session_date": self.reference_session_date,
            "_provider_market_status": self.provider_market_status,
            "ExchangeTime": self.source_timestamp,
            "is_realtime_eligible": display_eligible,
        }

    def to_wire_patch(self, updated_fields: Dict[str, Any]) -> Dict[str, Any]:
        """
        Constructs an incremental patch payload for the updated fields.
        """
        is_index = self.instrument_type == "INDEX"
        scale = 1.0 if is_index else 1000.0

        def to_wire_prc(val: Any) -> Any:
            if val is None:
                return None
            return round(float(val) / scale, 6)

        def to_wire_iv(val: Any) -> Any:
            if val is None:
                return None
            return round(float(val) * 100.0, 4)

        patch: Dict[str, Any] = {"Symbol": self.symbol}

        mapping = {
            "last_price": ("Traded", to_wire_prc),
            "reference_price": ("Ref", to_wire_prc),
            "ceiling_price": ("Ceil", to_wire_prc),
            "floor_price": ("Floor", to_wire_prc),
            "open_price": ("Open_Prc", to_wire_prc),
            "high_price": ("High_Prc", to_wire_prc),
            "low_price": ("Low_Prc", to_wire_prc),
            "average_price": ("Avg_Prc", to_wire_prc),
            "price_change": ("change", to_wire_prc),
            "price_change_percent": ("ChangePercent", lambda v: v),
            "total_volume": ("Total_Vol", lambda v: v),
            "traded_quantity": ("Traded_Qty", lambda v: v),
            "trading_value": ("Trading_Val", to_wire_prc),
            "bid1_price": ("Bid1_Prc", to_wire_prc),
            "bid1_quantity": ("Bid1_Qty", lambda v: v),
            "ask1_price": ("Ask1_Prc", to_wire_prc),
            "ask1_quantity": ("Ask1_Qty", lambda v: v),
            "bid2_price": ("Bid2_Prc", to_wire_prc),
            "bid2_quantity": ("Bid2_Qty", lambda v: v),
            "ask2_price": ("Ask2_Prc", to_wire_prc),
            "ask2_quantity": ("Ask2_Qty", lambda v: v),
            "bid3_price": ("Bid3_Prc", to_wire_prc),
            "bid3_quantity": ("Bid3_Qty", lambda v: v),
            "ask3_price": ("Ask3_Prc", to_wire_prc),
            "ask3_quantity": ("Ask3_Qty", lambda v: v),
            "underlying_price": ("Under_Prc", to_wire_prc),
            "iv_ask": ("Vol1", to_wire_iv),
            "iv_trade": ("Vol2", to_wire_iv),
            "iv_bid": ("Vol3", to_wire_iv),
            "source_timestamp": ("_ts_source", lambda v: v),
            "trade_timestamp": ("_ts_trade", lambda v: v),
            "book_timestamp": ("_ts_book", lambda v: v),
            "trade_received_timestamp": ("_received_trade", lambda v: v),
            "book_received_timestamp": ("_received_book", lambda v: v),
            "provider_market_status": ("_provider_market_status", lambda v: v),
            "market_session_date": ("_market_session_date", lambda v: v),
            "reference_timestamp": ("_ts_reference", lambda v: v),
            "reference_session_date": ("_reference_session_date", lambda v: v),
        }

        for field_name, (wire_key, transform_fn) in mapping.items():
            if field_name in updated_fields:
                patch[wire_key] = transform_fn(updated_fields[field_name])

        if "_ts_source" not in patch and self.source_timestamp:
            patch["_ts_source"] = self.source_timestamp

        return patch


class HistoricalBar(BaseModel):
    date: str = Field(..., description="ISO date or datetime string")
    open: float
    high: float
    low: float
    close: float
    volume: float
    value: Optional[float] = Field(default=None, description="Total traded value in VND")
    price_basis: Optional[Literal["RAW", "ADJUSTED"]] = None
    source: str = "FIINQUANT"
    session_date: Optional[str] = None
    adjusted: bool = Field(default=True, description="Whether prices are adjusted for corporate actions")


class HistoricalDataError(Exception):
    """Base exception for historical market data errors."""
    pass


class HistoricalRangeLimitError(HistoricalDataError):
    """Raised when a requested historical range exceeds the upstream provider's max lookback window (e.g. FiinQuant 365-day limit)."""
    pass


class HistoricalAuthError(HistoricalDataError):
    """Raised when historical request fails due to invalid or expired authentication credentials."""
    pass


class HistoricalEntitlementError(HistoricalDataError):
    """Raised when account lacks entitlement/permissions for the requested historical entity or dataset."""
    pass


class HistoricalRateLimitError(HistoricalDataError):
    """Raised when upstream returns HTTP 429 rate limit."""
    pass


class HistoricalTransportError(HistoricalDataError):
    """Raised when a network timeout or transport connection error occurs."""
    pass


class HistoricalUpstreamError(HistoricalDataError):
    """Raised when upstream server returns 5xx error."""
    pass


# Canonical reasons a historical circuit can be open. AUTH_FAILURE / ENTITLEMENT do not
# self-heal; RATE_LIMIT / UPSTREAM clear after their cooldown.
CIRCUIT_REASON_AUTH = "AUTH_FAILURE"
CIRCUIT_REASON_RATE_LIMIT = "RATE_LIMIT"
CIRCUIT_REASON_ENTITLEMENT = "ENTITLEMENT"
CIRCUIT_REASON_UPSTREAM = "UPSTREAM"
CIRCUIT_REASON_UNKNOWN = "UNKNOWN"

_SELF_HEALING_CIRCUIT_REASONS = frozenset({CIRCUIT_REASON_RATE_LIMIT, CIRCUIT_REASON_UPSTREAM})


class HistoricalCircuitOpenError(HistoricalDataError):
    """Raised when the provider's historical circuit breaker is currently OPEN and is
    rejecting the request *without contacting upstream*.

    Distinct from the underlying failure classes so callers never have to inspect message
    strings or hidden provider state to decide retryability:

      * ``reason`` - the canonical class of failure that opened the circuit
        (``AUTH_FAILURE`` / ``ENTITLEMENT`` / ``RATE_LIMIT`` / ``UPSTREAM`` / ``UNKNOWN``).
      * ``retry_after_seconds`` - best-effort remaining cooldown before the circuit
        half-opens.
      * ``is_retryable`` - True only when the circuit will clear on its own
        (rate-limit / transient upstream); an auth or entitlement circuit will not.
    """

    def __init__(self, message: str, *, reason: str, retry_after_seconds: float = 0.0):
        super().__init__(message)
        self.reason = reason or CIRCUIT_REASON_UNKNOWN
        self.retry_after_seconds = max(0.0, float(retry_after_seconds))

    @property
    def is_retryable(self) -> bool:
        return self.reason in _SELF_HEALING_CIRCUIT_REASONS


class MarketHealthResponse(BaseModel):
    status: str = "ok"
    provider: str
    authenticated: bool
    upstream_status: str
    trade_stream_connected: bool
    bid_ask_stream_connected: bool
    subscription_count: int
    max_subscriptions: int
    subscriptions: List[str]
    redis_enabled: bool = False
    redis_connected: bool = False
    market_cache_available: bool = False
    market_cache_counters: Dict[str, int] = Field(default_factory=dict)
    feed_fresh: bool = False
    last_trade_tick_at: Optional[str] = None
    last_book_tick_at: Optional[str] = None
    last_tick_at: Optional[str] = None
    signalr_decode_error_count: int = 0
    signalr_reconnect_count: int = 0
    realtime_universe: Dict[str, Any] = Field(default_factory=dict)
    market_session: str = "UNKNOWN"
    market_session_active: bool = False
    market_phase: str = "UNKNOWN"
    quote_display_eligible: bool = False


class StockProfile(BaseModel):
    symbol: str
    name: Optional[str] = None
    short_name: Optional[str] = None
    exchange: Optional[str] = None
    source: Optional[str] = None
    availability: Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"] = "UNAVAILABLE"


class StockProfilesResponse(BaseModel):
    items: List[StockProfile]


class ClientControlMessage(BaseModel):
    type: Literal["subscribe", "unsubscribe"]
    symbols: List[str]
