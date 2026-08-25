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
    source_timestamp: Optional[int] = None  # epoch ms
    received_timestamp: int = Field(default_factory=lambda: int(datetime.now(timezone.utc).timestamp() * 1000))

    def to_wire_snapshot_row(self) -> Dict[str, Any]:
        """
        Converts the canonical quote to the gateway wire format expected by the frontend.
        Note: The frontend normalizeTransportPriceToRawVnd multiplies by 1000 for transport price fields.
        For index (POINTS) or raw VND, we format accordingly:
        - For stocks & CWs: divide raw VND by 1000 so frontend x1000 yields exact raw VND.
        - For Index: points remain unchanged or formatted for frontend transport.
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

        return {
            "Symbol": self.symbol,
            "Traded": to_wire_prc(self.last_price),
            "Ref": to_wire_prc(self.reference_price),
            "Ceil": to_wire_prc(self.ceiling_price),
            "Floor": to_wire_prc(self.floor_price),
            "Open_Prc": to_wire_prc(self.open_price),
            "High_Prc": to_wire_prc(self.high_price),
            "Low_Prc": to_wire_prc(self.low_price),
            "Avg_Prc": to_wire_prc(self.average_price),
            "change": to_wire_prc(self.price_change),
            "ChangePercent": self.price_change_percent,
            "Total_Vol": self.total_volume,
            "Traded_Qty": self.traded_quantity,
            "Trading_Val": to_wire_prc(self.trading_value),
            "Bid1_Prc": to_wire_prc(self.bid1_price),
            "Bid1_Qty": self.bid1_quantity,
            "Ask1_Prc": to_wire_prc(self.ask1_price),
            "Ask1_Qty": self.ask1_quantity,
            "Bid2_Prc": to_wire_prc(self.bid2_price),
            "Bid2_Qty": self.bid2_quantity,
            "Ask2_Prc": to_wire_prc(self.ask2_price),
            "Ask2_Qty": self.ask2_quantity,
            "Bid3_Prc": to_wire_prc(self.bid3_price),
            "Bid3_Qty": self.bid3_quantity,
            "Ask3_Prc": to_wire_prc(self.ask3_price),
            "Ask3_Qty": self.ask3_quantity,
            "Under_Prc": to_wire_prc(self.underlying_price),
            "Strike_Prc": to_wire_prc(self.strike_price),
            "Ratio": self.exercise_ratio,
            "Under_Symbol": self.underlying_symbol,
            "Vol1": to_wire_iv(self.iv_ask),
            "Vol2": to_wire_iv(self.iv_trade),
            "Vol3": to_wire_iv(self.iv_bid),
            "LastTradingDate": self.last_trading_date,
            "MaturityDate": self.maturity_date,
            "_ts_source": self.source_timestamp,
            "ExchangeTime": self.source_timestamp,
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
    adjusted: bool = Field(default=True, description="Whether prices are adjusted for corporate actions")


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


class ClientControlMessage(BaseModel):
    type: Literal["subscribe", "unsubscribe"]
    symbols: List[str]
