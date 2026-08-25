import os
import sys
import logging
import asyncio
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, timedelta, timezone

# Ensure FiinQuantX vendor dependencies can be resolved if located in backend/poc/fiinquant/.venv
_poc_site = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..", "poc", "fiinquant", ".venv",
        "lib",
        f"python{sys.version_info.major}.{sys.version_info.minor}",
        "site-packages"
    )
)
if os.path.exists(_poc_site) and _poc_site not in sys.path:
    sys.path.insert(0, _poc_site)

from app.core.config import settings
from app.market.schemas import HistoricalBar
from app.market.providers.base import MarketDataProvider

logger = logging.getLogger(__name__)


class FiinQuantProvider(MarketDataProvider):
    """
    Production market data provider wrapping the official FiinQuant SDK (FiinQuantX).
    Safely bridges background thread SignalR callbacks into FastAPI's asyncio event loop.
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        max_symbols: Optional[int] = None,
    ):
        self.username = username or settings.FIINQUANT_USERNAME
        self.password = password or settings.FIINQUANT_PASSWORD
        self.max_symbols = max_symbols or settings.FIINQUANT_MAX_REALTIME_SYMBOLS

        self._session: Any = None
        self._trade_stream: Any = None
        self._bidask_stream: Any = None
        self._active_symbols: List[str] = []
        self._event_callback: Optional[Callable[[str, Dict[str, Any], str], None]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._is_connected = False
        self._upstream_status = "DISCONNECTED"

    def set_event_callback(self, callback: Callable[[str, Dict[str, Any], str], None]) -> None:
        self._event_callback = callback
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def _ensure_loop(self) -> None:
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

    def _on_trade_raw(self, data: Any) -> None:
        """Callback invoked by FiinQuant SDK Trading_Data_Stream on worker thread."""
        try:
            d = data.to_dict() if hasattr(data, "to_dict") else (data if isinstance(data, dict) else vars(data))
            sym = str(d.get("Ticker", "")).upper()
            if not sym:
                return

            self._ensure_loop()
            if self._loop and self._loop.is_running() and self._event_callback:
                self._loop.call_soon_threadsafe(self._event_callback, "trade", d, sym)
        except Exception as err:
            logger.warning(f"Error handling raw trade event: {err}")

    def _on_bidask_raw(self, data: Any) -> None:
        """Callback invoked by FiinQuant SDK BidAsk stream on worker thread."""
        try:
            d = data.to_dict() if hasattr(data, "to_dict") else (data if isinstance(data, dict) else vars(data))
            sym = str(d.get("Ticker", "")).upper()
            if not sym:
                return

            self._ensure_loop()
            if self._loop and self._loop.is_running() and self._event_callback:
                self._loop.call_soon_threadsafe(self._event_callback, "bidask", d, sym)
        except Exception as err:
            logger.warning(f"Error handling raw BidAsk event: {err}")

    async def connect(self) -> bool:
        """Authenticates with FiinQuant API gateway."""
        if not self.username or not self.password:
            logger.warning("FiinQuant credentials not configured in environment.")
            self._upstream_status = "UNAVAILABLE"
            return False

        self._ensure_loop()

        def _do_login():
            try:
                import FiinQuantX as fq  # type: ignore
                session = fq.FiinSession(username=self.username, password=self.password)
                session.login()
                is_logged_in = getattr(session, "is_login", False) or bool(getattr(session, "access_token", None))
                return session if is_logged_in else None
            except Exception as e:
                logger.error(f"FiinQuant authentication error: {e.__class__.__name__}")
                return None

        self._session = await asyncio.to_thread(_do_login)

        if self._session:
            self._is_connected = True
            self._upstream_status = "CONNECTED"
            logger.info("FiinQuant authentication successful. Upstream status: CONNECTED")
            return True
        else:
            self._is_connected = False
            self._upstream_status = "ERROR"
            logger.error("FiinQuant authentication failed.")
            return False

    async def disconnect(self) -> None:
        """Stops active streams and tears down session."""
        self._upstream_status = "DISCONNECTED"
        self._is_connected = False
        await self._stop_streams()
        self._session = None
        self._active_symbols = []
        logger.info("FiinQuant provider disconnected.")

    async def _stop_streams(self) -> None:
        """Helper to stop background SDK streams in thread."""
        trade_s = self._trade_stream
        ba_s = self._bidask_stream

        self._trade_stream = None
        self._bidask_stream = None

        def _do_stop():
            if trade_s:
                try:
                    trade_s.stop()
                except Exception as e:
                    logger.debug(f"Error stopping trade stream: {e}")
            if ba_s:
                try:
                    ba_s.stop()
                except Exception as e:
                    logger.debug(f"Error stopping bidask stream: {e}")

        await asyncio.to_thread(_do_stop)

    async def set_subscriptions(self, symbols: List[str]) -> bool:
        """
        Reconfigures active streaming subscriptions.
        FiinQuant SDK requires stream recreation: stops previous streams and creates new ones.
        """
        clean_symbols = list(dict.fromkeys([s.strip().upper() for s in symbols if s.strip()]))

        if len(clean_symbols) > self.max_symbols:
            logger.error(f"Requested {len(clean_symbols)} symbols exceeds capacity {self.max_symbols}")
            return False

        if not self._session or not self._is_connected:
            connected = await self.connect()
            if not connected:
                return False

        self._ensure_loop()
        self._upstream_status = "RESTARTING"

        # Stop existing streams
        await self._stop_streams()

        if not clean_symbols:
            self._active_symbols = []
            self._upstream_status = "CONNECTED"
            return True

        self._active_symbols = clean_symbols

        def _start_new_streams():
            try:
                # Separate tickers for trade and bidask
                # Note: Index (e.g. VNINDEX) doesn't have BidAsk order book depth on HOSE
                ba_symbols = [s for s in clean_symbols if s not in ("VNINDEX", "VN30", "HNXINDEX", "UPCOM")]

                trade_stream = self._session.Trading_Data_Stream(
                    tickers=clean_symbols,
                    callback=self._on_trade_raw,
                )
                trade_stream.start()

                bidask_stream = None
                if ba_symbols:
                    bidask_stream = self._session.BidAsk(
                        tickers=ba_symbols,
                        callback=self._on_bidask_raw,
                    )
                    bidask_stream.start()

                return trade_stream, bidask_stream
            except Exception as e:
                logger.error(f"Failed to start FiinQuant streams: {e}")
                return None, None

        ts, bs = await asyncio.to_thread(_start_new_streams)
        self._trade_stream = ts
        self._bidask_stream = bs
        self._upstream_status = "CONNECTED"

        logger.info(f"FiinQuant streams active for {len(clean_symbols)} symbols: {clean_symbols}")
        return True

    def get_active_subscriptions(self) -> List[str]:
        return list(self._active_symbols)

    def get_health(self) -> Dict[str, Any]:
        trade_conn = getattr(self._trade_stream, "connected", False) if self._trade_stream else False
        ba_conn = getattr(self._bidask_stream, "connected", False) if self._bidask_stream else False

        if not self._is_connected:
            computed_status = "UNAVAILABLE" if not self.username or not self.password else "ERROR"
        elif self._upstream_status == "RESTARTING":
            computed_status = "RESTARTING"
        elif not self._active_symbols:
            computed_status = "READY"
        elif trade_conn or ba_conn:
            computed_status = "LIVE"
        else:
            computed_status = "CONNECTING"

        return {
            "provider": "fiinquant",
            "authenticated": self._is_connected,
            "upstream_status": computed_status,
            "trade_stream_connected": trade_conn,
            "bid_ask_stream_connected": ba_conn,
            "subscription_count": len(self._active_symbols),
            "max_subscriptions": self.max_symbols,
            "subscriptions": self.get_active_subscriptions(),
        }

    async def get_historical_bars(
        self,
        symbol: str,
        timeframe: str = "1D",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        adjusted: bool = True,
    ) -> List[HistoricalBar]:
        """Fetches historical EOD bars via FiinQuant Fetch_Trading_Data."""
        if not self._session or not self._is_connected:
            connected = await self.connect()
            if not connected:
                return []

        sym = symbol.strip().upper()
        default_from = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        f_date = from_date or default_from
        t_date = to_date or datetime.now().strftime("%Y-%m-%d")

        def _fetch():
            try:
                res = self._session.Fetch_Trading_Data(
                    realtime=False,
                    tickers=[sym],
                    fields=["open", "high", "low", "close", "volume"],
                    from_date=f_date,
                    to_date=t_date,
                    adjusted=adjusted,
                )
                df = res.get_data() if hasattr(res, "get_data") else res
                bars: List[HistoricalBar] = []

                if hasattr(df, "to_dict"):
                    records = df.to_dict(orient="records")
                    for r in records:
                        d_str = str(r.get("timestamp") or r.get("TradingDate") or r.get("date") or "")
                        c_val = r.get("close") or r.get("Close")
                        if d_str and c_val is not None:
                            bars.append(
                                HistoricalBar(
                                    date=d_str,
                                    open=float(r.get("open") or r.get("Open") or c_val),
                                    high=float(r.get("high") or r.get("High") or c_val),
                                    low=float(r.get("low") or r.get("Low") or c_val),
                                    close=float(c_val),
                                    volume=float(r.get("volume") or r.get("Volume") or 0.0),
                                    adjusted=adjusted,
                                )
                            )
                return bars
            except Exception as e:
                logger.error(f"Error fetching historical bars for {sym}: {e}")
                return []

        return await asyncio.to_thread(_fetch)
