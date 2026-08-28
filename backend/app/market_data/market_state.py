import logging
from typing import Dict, List, Optional, Any, Tuple, Literal
from datetime import datetime, timezone
import threading

from app.market_data.market_schemas import CanonicalQuote
from app.market_data.market_session import market_session

logger = logging.getLogger(__name__)


class MarketState:
    """
    Thread-safe in-memory store for normalized market quotes.
    Merges matching trade streams and top-of-book depth streams into canonical quotes.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._quotes: Dict[str, CanonicalQuote] = {}

    def _determine_instrument_type(self, symbol: str) -> Literal["STOCK", "INDEX", "CW"]:
        sym = symbol.upper()
        if sym in ("VNINDEX", "VN30", "HNXINDEX", "UPCOM"):
            return "INDEX"
        elif len(sym) == 8 and sym.startswith("C"):
            return "CW"
        return "STOCK"

    def get_or_create_quote(self, symbol: str) -> CanonicalQuote:
        sym = symbol.upper()
        with self._lock:
            if sym not in self._quotes:
                inst_type = self._determine_instrument_type(sym)
                self._quotes[sym] = CanonicalQuote(symbol=sym, instrument_type=inst_type)
            return self._quotes[sym]

    def get_quote(self, symbol: str) -> Optional[CanonicalQuote]:
        with self._lock:
            q = self._quotes.get(symbol.upper())
            return q.model_copy() if q else None

    def has_quote(self, symbol: str) -> bool:
        with self._lock:
            return symbol.upper() in self._quotes

    def restore_quote(self, quote: CanonicalQuote) -> bool:
        """
        Restores a cached CanonicalQuote into active in-memory state.
        Never overwrites a newer live quote in memory.
        """
        sym = quote.symbol.upper()
        with self._lock:
            existing = self._quotes.get(sym)
            if existing:
                existing_ts = existing.received_timestamp or existing.source_timestamp or 0
                incoming_ts = quote.received_timestamp or quote.source_timestamp or 0
                if existing_ts >= incoming_ts:
                    return False
            self._quotes[sym] = quote.model_copy()
            return True

    def restore_quotes(self, quotes: Dict[str, CanonicalQuote]) -> int:
        restored = 0
        for sym, quote in quotes.items():
            if self.restore_quote(quote):
                restored += 1
        return restored

    def get_all_quotes(self) -> Dict[str, CanonicalQuote]:
        with self._lock:
            return {k: v.model_copy() for k, v in self._quotes.items()}

    def get_snapshots(self, symbols: List[str], display_eligible_only: bool = True) -> List[Dict[str, Any]]:
        is_eligible = market_session.is_trading_active() if display_eligible_only else True
        with self._lock:
            rows = []
            for s in symbols:
                sym = s.upper()
                if sym in self._quotes:
                    rows.append(self._quotes[sym].to_wire_snapshot_row(display_eligible=is_eligible))
            return rows

    def apply_trade_event(self, raw_event: Dict[str, Any]) -> Tuple[CanonicalQuote, Dict[str, Any]]:
        """
        Merges a matching trade event from Trading_Data_Stream into canonical state.
        Returns the updated CanonicalQuote and a dictionary of updated fields for patching.
        """
        sym = str(raw_event.get("Ticker", "")).upper()
        if not sym:
            raise ValueError("Missing Ticker in trade event")

        inst_type = self._determine_instrument_type(sym)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        # Parse raw price (FiinQuant runtime verified: raw VND for Stock/CW, points for Index)
        match_price = raw_event.get("Close")
        if match_price is None:
            match_price = raw_event.get("MatchPrice")
        if match_price is None:
            match_price = raw_event.get("Price")

        ref_price = raw_event.get("ReferencePrice")
        if ref_price is None:
            ref_price = raw_event.get("RefPrice")

        ceil_price = raw_event.get("CeilingPrice")
        floor_price = raw_event.get("FloorPrice")

        open_price = raw_event.get("Open")
        if open_price is None:
            open_price = raw_event.get("OpenPrice")

        high_price = raw_event.get("High")
        if high_price is None:
            high_price = raw_event.get("HighPrice")

        low_price = raw_event.get("Low")
        if low_price is None:
            low_price = raw_event.get("LowPrice")

        avg_price = raw_event.get("AveragePrice")

        change = raw_event.get("Change")
        if change is None:
            change = raw_event.get("change")
        if change is None:
            change = raw_event.get("PriceChange")

        change_pct = raw_event.get("ChangePercent")
        if change_pct is None:
            change_pct = raw_event.get("ChangeRate")
        if change_pct is None:
            change_pct = raw_event.get("change_percent")

        tot_vol = raw_event.get("TotalMatchVolume")
        if tot_vol is None:
            tot_vol = raw_event.get("TotalVolume")
        if tot_vol is None:
            tot_vol = raw_event.get("Volume")

        traded_qty = raw_event.get("MatchVolume")
        if traded_qty is None:
            traded_qty = raw_event.get("TradedVolume")

        tot_val = raw_event.get("TotalMatchValue")
        if tot_val is None:
            tot_val = raw_event.get("TotalValue")

        trading_date = raw_event.get("TradingDate")
        ts_str = raw_event.get("Timestamp")

        # Parse source timestamp in ms
        source_ts = None
        if trading_date:
            try:
                # e.g., 2026-08-25T09:28:23.5380000+07:00
                dt = datetime.fromisoformat(trading_date)
                source_ts = int(dt.timestamp() * 1000)
            except Exception:
                pass
        if not source_ts and ts_str:
            try:
                dt = datetime.fromisoformat(ts_str)
                source_ts = int(dt.timestamp() * 1000)
            except Exception:
                pass

        diff: Dict[str, Any] = {}

        with self._lock:
            if sym not in self._quotes:
                self._quotes[sym] = CanonicalQuote(symbol=sym, instrument_type=inst_type)

            q = self._quotes[sym]

            if match_price is not None and q.last_price != float(match_price):
                q.last_price = float(match_price)
                diff["last_price"] = q.last_price

            if ref_price is not None and q.reference_price != float(ref_price):
                q.reference_price = float(ref_price)
                diff["reference_price"] = q.reference_price

            if ceil_price is not None and q.ceiling_price != float(ceil_price):
                q.ceiling_price = float(ceil_price)
                diff["ceiling_price"] = q.ceiling_price

            if floor_price is not None and q.floor_price != float(floor_price):
                q.floor_price = float(floor_price)
                diff["floor_price"] = q.floor_price

            if open_price is not None and q.open_price != float(open_price):
                q.open_price = float(open_price)
                diff["open_price"] = q.open_price

            if high_price is not None and q.high_price != float(high_price):
                q.high_price = float(high_price)
                diff["high_price"] = q.high_price

            if low_price is not None and q.low_price != float(low_price):
                q.low_price = float(low_price)
                diff["low_price"] = q.low_price

            if avg_price is not None and q.average_price != float(avg_price):
                q.average_price = float(avg_price)
                diff["average_price"] = q.average_price

            if change is not None and q.price_change != float(change):
                q.price_change = float(change)
                diff["price_change"] = q.price_change

            if change_pct is not None and q.price_change_percent != float(change_pct):
                q.price_change_percent = float(change_pct)
                diff["price_change_percent"] = q.price_change_percent

            if tot_vol is not None and q.total_volume != int(tot_vol):
                q.total_volume = int(tot_vol)
                diff["total_volume"] = q.total_volume

            if traded_qty is not None and q.traded_quantity != int(traded_qty):
                q.traded_quantity = int(traded_qty)
                diff["traded_quantity"] = q.traded_quantity

            if tot_val is not None and q.trading_value != float(tot_val):
                q.trading_value = float(tot_val)
                diff["trading_value"] = q.trading_value

            if trading_date:
                q.provider_trading_date = str(trading_date)
            if ts_str:
                q.provider_timestamp = str(ts_str)
            if source_ts:
                q.source_timestamp = source_ts
                diff["source_timestamp"] = source_ts

            q.received_timestamp = now_ms

            return q.model_copy(), diff

    def apply_bidask_event(self, raw_event: Dict[str, Any]) -> Tuple[CanonicalQuote, Dict[str, Any]]:
        """
        Merges an order-book depth event from BidAsk stream into canonical state.
        Crucial: Never modifies last_price if no trade occurred.
        """
        sym = str(raw_event.get("Ticker", "")).upper()
        if not sym:
            raise ValueError("Missing Ticker in BidAsk event")

        inst_type = self._determine_instrument_type(sym)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        def get_field(*keys):
            for k in keys:
                val = raw_event.get(k)
                if val is not None:
                    return val
            return None

        # Depth 1
        b1_prc = get_field("Best1Bid", "BidPrice1", "Bid1")
        b1_vol = get_field("Best1BidVolume", "BidVol1", "Bid1Vol")
        a1_prc = get_field("Best1Ask", "AskPrice1", "Ask1")
        a1_vol = get_field("Best1AskVolume", "AskVol1", "Ask1Vol")

        # Depth 2
        b2_prc = get_field("Best2Bid", "BidPrice2")
        b2_vol = get_field("Best2BidVolume", "BidVol2")
        a2_prc = get_field("Best2Ask", "AskPrice2")
        a2_vol = get_field("Best2AskVolume", "AskVol2")

        # Depth 3
        b3_prc = get_field("Best3Bid", "BidPrice3")
        b3_vol = get_field("Best3BidVolume", "BidVol3")
        a3_prc = get_field("Best3Ask", "AskPrice3")
        a3_vol = get_field("Best3AskVolume", "AskVol3")

        ts_str = raw_event.get("Timestamp")
        source_ts = None
        if ts_str:
            try:
                dt = datetime.fromisoformat(ts_str)
                source_ts = int(dt.timestamp() * 1000)
            except Exception:
                pass

        diff: Dict[str, Any] = {}

        with self._lock:
            if sym not in self._quotes:
                self._quotes[sym] = CanonicalQuote(symbol=sym, instrument_type=inst_type)

            q = self._quotes[sym]

            # Level 1
            if b1_prc is not None and q.bid1_price != float(b1_prc):
                q.bid1_price = float(b1_prc)
                diff["bid1_price"] = q.bid1_price

            if b1_vol is not None and q.bid1_quantity != int(b1_vol):
                q.bid1_quantity = int(b1_vol)
                diff["bid1_quantity"] = q.bid1_quantity

            if a1_prc is not None and q.ask1_price != float(a1_prc):
                q.ask1_price = float(a1_prc)
                diff["ask1_price"] = q.ask1_price

            if a1_vol is not None and q.ask1_quantity != int(a1_vol):
                q.ask1_quantity = int(a1_vol)
                diff["ask1_quantity"] = q.ask1_quantity

            # Level 2
            if b2_prc is not None and q.bid2_price != float(b2_prc):
                q.bid2_price = float(b2_prc)
                diff["bid2_price"] = q.bid2_price

            if b2_vol is not None and q.bid2_quantity != int(b2_vol):
                q.bid2_quantity = int(b2_vol)
                diff["bid2_quantity"] = q.bid2_quantity

            if a2_prc is not None and q.ask2_price != float(a2_prc):
                q.ask2_price = float(a2_prc)
                diff["ask2_price"] = q.ask2_price

            if a2_vol is not None and q.ask2_quantity != int(a2_vol):
                q.ask2_quantity = int(a2_vol)
                diff["ask2_quantity"] = q.ask2_quantity

            # Level 3
            if b3_prc is not None and q.bid3_price != float(b3_prc):
                q.bid3_price = float(b3_prc)
                diff["bid3_price"] = q.bid3_price

            if b3_vol is not None and q.bid3_quantity != int(b3_vol):
                q.bid3_quantity = int(b3_vol)
                diff["bid3_quantity"] = q.bid3_quantity

            if a3_prc is not None and q.ask3_price != float(a3_prc):
                q.ask3_price = float(a3_prc)
                diff["ask3_price"] = q.ask3_price

            if a3_vol is not None and q.ask3_quantity != int(a3_vol):
                q.ask3_quantity = int(a3_vol)
                diff["ask3_quantity"] = q.ask3_quantity

            if ts_str:
                q.provider_timestamp = str(ts_str)
            if source_ts:
                q.source_timestamp = source_ts
                diff["source_timestamp"] = source_ts

            q.received_timestamp = now_ms

            return q.model_copy(), diff


# Global market state instance
market_state = MarketState()
