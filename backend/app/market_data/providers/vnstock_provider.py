"""Vnstock Community adapter for the terminal's canonical market-data contract.

The public Vnstock package is an HTTP retrieval library rather than a realtime stream.
This adapter owns one bounded polling lifecycle, rate-limits every upstream call across
quote/history/tape/overview, and emits the same canonical events the rest of the terminal
already consumes. KBS board values are raw VND, while Vnstock's KBS/VCI history and tape
helpers expose non-index prices in thousands of VND; normalization happens here once.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import math
import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# The package starts a background agent-bootstrap writer on import. A production market
# adapter must not edit repository or global AI configuration files as a side effect.
os.environ.setdefault("VNSTOCK_DISABLE_AGENT_SETUP", "1")
os.environ.setdefault("VNSTOCK_DISABLE_GLOBAL_AGENT", "1")

from app.core.config import settings
from app.market_data.feed_status import FeedAccess, classify_provider_error
from app.market_data.market_schemas import (
    HistoricalAuthError,
    HistoricalBar,
    HistoricalEntitlementError,
    HistoricalRateLimitError,
    HistoricalTransportError,
    HistoricalUpstreamError,
)
from app.market_data.market_session import market_session
from app.market_data.providers.base_market_provider import MarketDataProvider
from app.market_data.trading_calendar import (
    VN_TZ,
    intraday_bar_is_complete,
    latest_completed_trading_session,
    reference_session_date,
)

EventCallback = Callable[[str, dict[str, Any], str], None]
logger = logging.getLogger(__name__)


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _integer(value: Any) -> int | None:
    number = _finite(value)
    return None if number is None else int(number)


def _records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if hasattr(value, "to_dict"):
        try:
            value = value.to_dict(orient="records")
        except TypeError:
            value = value.to_dict()
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, dict)]
    return [dict(value)] if isinstance(value, dict) else []


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).replace(tzinfo=VN_TZ).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _iso_timestamp(value: Any, *, session_date: str | None = None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        number = _finite(value)
        if number is not None and number > 10_000_000_000:
            dt = datetime.fromtimestamp(number / 1000.0, tz=VN_TZ)
        elif number is not None and number > 1_000_000_000:
            dt = datetime.fromtimestamp(number, tz=VN_TZ)
        else:
            text = str(value).strip().replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(text)
            except ValueError:
                if session_date and len(text) >= 8:
                    try:
                        dt = datetime.fromisoformat(f"{session_date}T{text[:8]}")
                    except ValueError:
                        return None
                else:
                    return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VN_TZ)
    return dt.astimezone(VN_TZ).isoformat()


def _is_index(symbol: str) -> bool:
    return symbol.upper() in {
        "VNINDEX", "VN30", "VN30INDEX", "VNFINLEAD", "VNDIAMOND",
        "HNXINDEX", "HNX30", "UPCOM", "UPCOMINDEX",
    }


def _is_cw(symbol: str) -> bool:
    value = symbol.upper()
    return len(value) == 8 and value.startswith("C")


def _raw_price(symbol: str, value: Any, *, already_raw: bool) -> float | None:
    number = _finite(value)
    if number is None:
        return None
    return number if already_raw or _is_index(symbol) else number * 1000.0


class VnstockProvider(MarketDataProvider):
    """Polling adapter backed by public Vnstock KBS/VCI sources."""

    _PROFILE_TTL = 6 * 3600.0
    _FUNDAMENTAL_TTL = 6 * 3600.0
    _OVERVIEW_TTL = 60.0
    _vendor_output_lock = threading.Lock()

    def __init__(
        self,
        *,
        max_symbols: int | None = None,
        board_fetcher: Callable[[list[str]], Any] | None = None,
        history_fetcher: Callable[..., Any] | None = None,
        tape_fetcher: Callable[[str, int], Any] | None = None,
        listing_fetcher: Callable[[], Any] | None = None,
        group_fetcher: Callable[[str], Any] | None = None,
        fundamentals_fetcher: Callable[[str], Any] | None = None,
    ) -> None:
        self.max_symbols = int(max_symbols or settings.MARKET_DATA_MAX_SYMBOLS)
        self._enabled = bool(settings.VNSTOCK_ENABLED)
        self._quote_interval = max(1.0, float(settings.VNSTOCK_QUOTE_POLL_SECONDS))
        self._tape_sweep = max(30.0, float(settings.VNSTOCK_TAPE_SWEEP_SECONDS))
        self._tape_page_size = max(1, min(1000, int(settings.VNSTOCK_TAPE_PAGE_SIZE)))
        self._freshness = max(self._quote_interval * 2, float(settings.VNSTOCK_FEED_FRESHNESS_SECONDS))
        self._request_floor = max(0.0, float(settings.VNSTOCK_MIN_REQUEST_INTERVAL_SECONDS))
        self._api_key_present = bool(settings.VNSTOCK_API_KEY.strip()) or (
            Path.home() / ".vnstock" / "api_key.json"
        ).is_file()
        if settings.VNSTOCK_API_KEY.strip():
            os.environ.setdefault("VNSTOCK_API_KEY", settings.VNSTOCK_API_KEY.strip())

        self._board_fetcher = board_fetcher or self._fetch_board_sync
        self._history_fetcher = history_fetcher or self._fetch_history_sync
        self._tape_fetcher = tape_fetcher or self._fetch_tape_sync
        self._listing_fetcher = listing_fetcher or self._fetch_listing_sync
        self._group_fetcher = group_fetcher or self._fetch_group_sync
        self._fundamentals_fetcher = fundamentals_fetcher or self._fetch_fundamentals_sync

        self._callback: EventCallback | None = None
        self._status_callback: Callable[[], None] | None = None
        self._access = FeedAccess()
        self._connected = False
        self._active_symbols: list[str] = []
        self._generation = 0
        self._quote_task: asyncio.Task | None = None
        self._tape_task: asyncio.Task | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._rate_lock = asyncio.Lock()
        self._call_semaphore = asyncio.Semaphore(max(1, int(settings.VNSTOCK_MAX_CONCURRENT_CALLS)))
        self._next_request_at = 0.0
        self._board_lock = asyncio.Lock()

        self._last_board_check_monotonic: float | None = None
        self._last_data_at_ms: int | None = None
        self._last_data_session: str | None = None
        self._last_trade_at_ms: int | None = None
        self._last_book_at_ms: int | None = None
        self._last_error_code: str | None = None
        self._request_count = 0
        self._request_failures = 0
        self._seen_prints: dict[str, deque[str]] = defaultdict(lambda: deque(maxlen=4000))
        self._seen_print_sets: dict[str, set[str]] = defaultdict(set)

        self._listing_cache: tuple[float, list[dict[str, Any]]] = (0.0, [])
        self._group_cache: dict[str, tuple[float, list[str]]] = {}
        self._fundamental_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._overview_cache: tuple[float, dict[str, Any] | None] = (0.0, None)
        self._board_cache_at = 0.0
        self._board_cache_requested: set[str] = set()
        self._board_cache: dict[str, dict[str, Any]] = {}

    # ------------------------------- lifecycle -------------------------------
    def set_event_callback(self, callback: EventCallback) -> None:
        self._callback = callback

    def set_status_callback(self, callback: Callable[[], None]) -> None:
        self._status_callback = callback

    def _notify_status(self) -> None:
        if self._status_callback is not None:
            try:
                self._status_callback()
            except Exception as exc:  # noqa: BLE001 - health listeners cannot break ingestion
                logger.debug("Vnstock status listener failed: %s", type(exc).__name__)

    async def connect(self) -> bool:
        if not self._enabled:
            self._connected = False
            return False
        try:
            import importlib.util

            if importlib.util.find_spec("vnstock") is None:
                self._access.record("authentication", "auth_required: vnstock package unavailable")
                self._connected = False
                return False
        except (ImportError, AttributeError, ValueError):
            self._connected = False
            return False
        self._connected = True
        self._notify_status()
        return True

    async def disconnect(self) -> None:
        async with self._lifecycle_lock:
            self._generation += 1
            tasks = [task for task in (self._quote_task, self._tape_task) if task is not None]
            self._quote_task = self._tape_task = None
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._active_symbols = []
            self._connected = False
        self._notify_status()

    async def set_subscriptions(self, symbols: list[str]) -> bool:
        clean = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
        if len(clean) > self.max_symbols:
            return False
        if not self._connected and not await self.connect():
            return False
        async with self._lifecycle_lock:
            self._generation += 1
            generation = self._generation
            old = [task for task in (self._quote_task, self._tape_task) if task is not None]
            for task in old:
                task.cancel()
            if old:
                await asyncio.gather(*old, return_exceptions=True)
            self._active_symbols = clean
            self._quote_task = self._tape_task = None
            if clean:
                self._quote_task = asyncio.create_task(self._run_quote_poll(generation))
                self._tape_task = asyncio.create_task(self._run_tape_sweep(generation))
        self._notify_status()
        return True

    def get_active_subscriptions(self) -> list[str]:
        return list(self._active_symbols)

    # ------------------------------ call boundary ----------------------------
    async def _wait_for_rate_slot(self) -> None:
        async with self._rate_lock:
            now = time.monotonic()
            delay = self._next_request_at - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_request_at = time.monotonic() + self._request_floor

    @classmethod
    def _silenced_sync_call(cls, func: Callable, *args: Any) -> Any:
        # Vnstock prints login/tier/account banners from decorators. They are irrelevant to
        # terminal users and can contain account identity, so keep them at the adapter edge.
        with cls._vendor_output_lock, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return func(*args)

    async def _call(self, scope: str, func: Callable, *args: Any) -> Any:
        blocked = self._access.blocked(scope)
        if blocked:
            raise RuntimeError(blocked)
        await self._wait_for_rate_slot()
        async with self._call_semaphore:
            self._request_count += 1
            try:
                result = await asyncio.to_thread(self._silenced_sync_call, func, *args)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._request_failures += 1
                self._last_error_code = self._access.record(scope, exc)
                if self._last_error_code is None:
                    self._last_error_code = self._access.record(scope, "upstream_unavailable")
                self._notify_status()
                raise
        self._access.success(scope)
        self._last_error_code = None
        return result

    @staticmethod
    def _fetch_board_sync(symbols: list[str]) -> Any:
        from vnstock.explorer.kbs.trading import Trading

        return Trading(show_log=False).price_board(symbols, get_all=True, show_log=False)

    @staticmethod
    def _fetch_tape_sync(symbol: str, page_size: int) -> Any:
        from vnstock.explorer.kbs.quote import Quote

        return Quote(symbol, show_log=False).intraday(
            page=1, page_size=page_size, get_all=True, floating=None, show_log=False
        )

    @staticmethod
    def _fetch_history_sync(
        symbol: str, source: str, start: str, end: str, interval: str
    ) -> Any:
        if source == "vci":
            from vnstock.explorer.vci.quote import Quote

            return Quote(symbol, show_log=False).history(
                start=start, end=end, interval=interval, floating=None, show_log=False
            )
        from vnstock.explorer.kbs.quote import Quote

        return Quote(symbol, show_log=False).history(
            start=start, end=end, interval=interval, floating=None, get_all=True, show_log=False
        )

    @staticmethod
    def _fetch_listing_sync() -> Any:
        from vnstock.explorer.vci.listing import Listing

        return Listing(show_log=False).symbols_by_exchange(show_log=False)

    @staticmethod
    def _fetch_group_sync(group: str) -> Any:
        from vnstock.explorer.vci.listing import Listing

        return Listing(show_log=False).symbols_by_group(group=group, show_log=False)

    @staticmethod
    def _fetch_fundamentals_sync(symbol: str) -> Any:
        from vnstock.explorer.vci.company import Company

        return Company(symbol, show_log=False).ratio_summary()

    # ------------------------------ live polling -----------------------------
    async def _run_quote_poll(self, generation: int) -> None:
        while self._connected and generation == self._generation:
            started = time.monotonic()
            try:
                if self._active_symbols:
                    await self._poll_quotes_once(generation)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the paced poller must survive vendor faults
                logger.debug("Vnstock quote poll unavailable: %s", type(exc).__name__)
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(0.2, self._quote_interval - elapsed))

    async def _poll_quotes_once(self, generation: int | None = None) -> int:
        symbols = list(self._active_symbols)
        if not symbols:
            return 0
        rows = list((await self._board_rows(symbols, "stream", max_age=0.0)).values())
        if generation is not None and generation != self._generation:
            return 0
        self._last_board_check_monotonic = time.monotonic()
        emitted = 0
        for row in rows:
            symbol = str(row.get("symbol") or row.get("SB") or "").strip().upper()
            if symbol not in symbols:
                continue
            session = _date_text(row.get("TD") or row.get("trading_date"))
            stamp = _iso_timestamp(row.get("time"), session_date=session)
            if stamp is None:
                stamp = _iso_timestamp(row.get("IT"), session_date=session)
            stamp_ms: int | None = None
            if stamp:
                stamp_ms = int(datetime.fromisoformat(stamp).timestamp() * 1000)
                self._last_data_at_ms = max(self._last_data_at_ms or 0, stamp_ms)
                self._last_book_at_ms = max(self._last_book_at_ms or 0, stamp_ms)
                self._last_data_session = max(self._last_data_session or "", session or "") or None
            trade_event = self._trade_event(row, symbol, session, stamp)
            book_event = self._book_event(row, symbol, session, stamp)
            if self._callback is not None and trade_event is not None:
                self._callback("trade", trade_event, symbol)
                emitted += 1
                if stamp_ms is not None and _finite(row.get("close_price")) not in (None, 0):
                    self._last_trade_at_ms = max(self._last_trade_at_ms or 0, stamp_ms)
            if self._callback is not None and book_event is not None:
                self._callback("bidask", book_event, symbol)
                emitted += 1
        self._notify_status()
        return emitted

    @staticmethod
    def _trade_event(row: dict[str, Any], symbol: str, session: str | None, stamp: str | None) -> dict[str, Any] | None:
        if not session:
            return None
        percent_change = _finite(row.get("percent_change"))
        return {
            "Ticker": symbol,
            "Close": _finite(row.get("close_price")),
            "Reference": _finite(row.get("reference_price")),
            "CeilingPrice": _finite(row.get("ceiling_price")),
            "FloorPrice": _finite(row.get("floor_price")),
            "Open": _finite(row.get("open_price")),
            "High": _finite(row.get("high_price")),
            "Low": _finite(row.get("low_price")),
            "AveragePrice": _finite(row.get("average_price")),
            "Change": _finite(row.get("price_change")),
            "PercentPriceChange": percent_change / 100.0 if percent_change is not None else None,
            "TotalMatchVolume": _integer(row.get("volume_accumulated")),
            "TotalMatchValue": _finite(row.get("total_value")),
            "TradingDate": session,
            "Timestamp": stamp,
            "MarketStatus": row.get("market_status") or row.get("MS"),
            "_synthetic_session_snapshot": True,
            "_provider_source": "VNSTOCK_KBS_PRICE_BOARD",
        }

    @staticmethod
    def _book_event(row: dict[str, Any], symbol: str, session: str | None, stamp: str | None) -> dict[str, Any] | None:
        if not session:
            return None
        return {
            "Ticker": symbol,
            "Best1Bid": _finite(row.get("bid_price_1")),
            "Best1BidVolume": _integer(row.get("bid_vol_1")),
            "Best2Bid": _finite(row.get("bid_price_2")),
            "Best2BidVolume": _integer(row.get("bid_vol_2")),
            "Best3Bid": _finite(row.get("bid_price_3")),
            "Best3BidVolume": _integer(row.get("bid_vol_3")),
            "Best1Ask": _finite(row.get("ask_price_1")),
            "Best1AskVolume": _integer(row.get("ask_vol_1")),
            "Best2Ask": _finite(row.get("ask_price_2")),
            "Best2AskVolume": _integer(row.get("ask_vol_2")),
            "Best3Ask": _finite(row.get("ask_price_3")),
            "Best3AskVolume": _integer(row.get("ask_vol_3")),
            "TradingDate": session,
            "Timestamp": stamp,
            "MarketStatus": row.get("market_status") or row.get("MS"),
            "_provider_source": "VNSTOCK_KBS_PRICE_BOARD",
        }

    async def _run_tape_sweep(self, generation: int) -> None:
        cursor = 0
        while self._connected and generation == self._generation:
            symbols = list(self._active_symbols)
            if not symbols or not market_session.is_trading_active():
                await asyncio.sleep(2.0)
                continue
            symbol = symbols[cursor % len(symbols)]
            cursor += 1
            try:
                rows = _records(await self._call("tape", self._tape_fetcher, symbol, self._tape_page_size))
                if generation == self._generation:
                    self._emit_confirmed_prints(symbol, rows)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the paced poller must survive vendor faults
                logger.debug("Vnstock tape poll unavailable: %s", type(exc).__name__)
            await asyncio.sleep(max(1.0, self._tape_sweep / max(1, len(symbols))))

    def _emit_confirmed_prints(self, symbol: str, rows: list[dict[str, Any]]) -> None:
        current = reference_session_date().isoformat()
        normalized: list[dict[str, Any]] = []
        for row in rows:
            session = _date_text(row.get("trading_date")) or _date_text(row.get("time"))
            if session != current:
                continue
            stamp = _iso_timestamp(row.get("time"), session_date=session)
            price = _raw_price(symbol, row.get("price"), already_raw=False)
            volume = _integer(row.get("volume"))
            cumulative = _integer(row.get("accumulated_volume"))
            if stamp is None or price is None or price <= 0 or volume is None or volume <= 0:
                continue
            provider_id = str(row.get("id") or "")
            identity = "|".join(map(str, (session, stamp, price, volume, cumulative, provider_id)))
            normalized.append({
                "Ticker": symbol,
                "Close": price,
                "MatchVolume": volume,
                "TotalMatchVolume": cumulative,
                "TotalMatchValue": _finite(row.get("accumulated_value")),
                "Change": _raw_price(symbol, row.get("price_change"), already_raw=False),
                "TradingDate": session,
                "Timestamp": stamp,
                "Side": str(row.get("match_type") or "").lower() or None,
                "TradeId": identity,
                "_provider_source": "VNSTOCK_KBS_TAPE",
            })
        normalized.sort(key=lambda item: item["Timestamp"])
        seen = self._seen_print_sets[symbol]
        order = self._seen_prints[symbol]
        for event in normalized:
            identity = event["TradeId"]
            if identity in seen:
                continue
            if len(order) == order.maxlen:
                seen.discard(order[0])
            order.append(identity)
            seen.add(identity)
            if self._callback is not None:
                self._callback("trade_print", event, symbol)

    # ----------------------------- snapshots/history -------------------------
    async def _board_rows(
        self, symbols: list[str], scope: str, *, max_age: float | None = None
    ) -> dict[str, dict[str, Any]]:
        clean = sorted({s.strip().upper() for s in symbols if s.strip()})
        if not clean:
            return {}
        freshness = self._quote_interval if max_age is None else max(0.0, max_age)

        def cached() -> dict[str, dict[str, Any]] | None:
            if (
                time.monotonic() - self._board_cache_at <= freshness
                and set(clean).issubset(self._board_cache_requested)
            ):
                return {symbol: self._board_cache[symbol] for symbol in clean if symbol in self._board_cache}
            return None

        hit = cached()
        if hit is not None:
            return hit
        async with self._board_lock:
            hit = cached()
            if hit is not None:
                return hit
            records: list[dict[str, Any]] = []
            # Keep request payloads bounded. The Vnstock API exposes a symbol-list
            # argument but does not document an unlimited list size.
            for offset in range(0, len(clean), 100):
                records.extend(_records(await self._call(
                    scope, self._board_fetcher, clean[offset:offset + 100]
                )))
            mapped = {
                str(row.get("symbol") or row.get("SB") or "").strip().upper(): row
                for row in records if str(row.get("symbol") or row.get("SB") or "").strip()
            }
            self._board_cache_at = time.monotonic()
            self._board_cache_requested = set(clean)
            self._board_cache = mapped
            return mapped

    async def get_session_reference_data(self, symbols: list[str], session_date: date) -> dict[str, dict[str, Any]]:
        rows = await self._board_rows(symbols, "session_reference")
        wanted = session_date.isoformat()
        result: dict[str, dict[str, Any]] = {}
        for symbol, row in rows.items():
            if _date_text(row.get("TD") or row.get("trading_date")) != wanted:
                continue
            result[symbol] = {
                "reference_price": _finite(row.get("reference_price")),
                "ceiling_price": _finite(row.get("ceiling_price")),
                "floor_price": _finite(row.get("floor_price")),
                "as_of": _iso_timestamp(row.get("time"), session_date=wanted),
                "session_date": wanted,
                "source": "VNSTOCK_KBS_PRICE_BOARD",
            }
        return result

    async def get_session_trade_snapshot(self, symbols: list[str], session_date: date) -> dict[str, dict[str, Any]]:
        rows = await self._board_rows(symbols, "session_snapshot")
        wanted = session_date.isoformat()
        result: dict[str, dict[str, Any]] = {}
        for symbol, row in rows.items():
            if _date_text(row.get("TD") or row.get("trading_date")) != wanted:
                continue
            result[symbol] = {
                "last_price": _finite(row.get("close_price")),
                "reference_price": _finite(row.get("reference_price")),
                "open_price": _finite(row.get("open_price")),
                "high_price": _finite(row.get("high_price")),
                "low_price": _finite(row.get("low_price")),
                "total_volume": _integer(row.get("volume_accumulated")),
                "trading_value": _finite(row.get("total_value")),
                "as_of": _iso_timestamp(row.get("time"), session_date=wanted),
                "session_date": wanted,
                "source": "VNSTOCK_KBS_PRICE_BOARD",
            }
        return result

    async def get_historical_bars(
        self,
        symbol: str,
        timeframe: str = "1D",
        from_date: str | None = None,
        to_date: str | None = None,
        adjusted: bool = True,
    ) -> list[HistoricalBar]:
        sym = symbol.strip().upper()
        normalized = timeframe.strip().lower()
        interval_map = {
            "1m": "1m", "1min": "1m", "5m": "5m", "5min": "5m",
            "15m": "15m", "15min": "15m", "30m": "30m", "30min": "30m",
            "1h": "1H", "60m": "1H", "1d": "1D", "d": "1D", "daily": "1D",
            "1w": "1W", "weekly": "1W", "1mth": "1M", "monthly": "1M",
        }
        interval = interval_map.get(normalized, "1D")
        default_days = 400 if interval == "1D" else 7
        end = to_date or market_session.get_vn_now().date().isoformat()
        start = from_date or (date.fromisoformat(end[:10]) - timedelta(days=default_days)).isoformat()
        requested_start = date.fromisoformat(start[:10])
        requested_end = date.fromisoformat(end[:10])

        # VCI's chart history is a restated adjusted series for equities. KBS is used for
        # as-traded RAW data and every CW. Indices have no corporate-action basis.
        use_adjusted = bool(adjusted and not _is_cw(sym) and not _is_index(sym) and interval == "1D")
        source_name = "vci" if use_adjusted or _is_index(sym) else "kbs"
        try:
            rows = _records(await self._call("history", self._history_fetcher, sym, source_name, start, end, interval))
        except Exception as exc:
            code = classify_provider_error(exc)
            if code == "AUTH_REQUIRED":
                raise HistoricalAuthError("Vnstock authentication is unavailable") from exc
            if code in ("ENTITLEMENT_EXPIRED", "DATASET_FORBIDDEN"):
                raise HistoricalEntitlementError("Vnstock historical dataset is unavailable") from exc
            if code == "RATE_LIMITED":
                raise HistoricalRateLimitError("Vnstock rate limit reached") from exc
            if code == "UPSTREAM_UNAVAILABLE":
                raise HistoricalTransportError("Vnstock historical transport is unavailable") from exc
            raise HistoricalUpstreamError("Vnstock returned no usable historical data") from exc

        now_vn = market_session.get_vn_now()
        completed_day = latest_completed_trading_session(now_vn)
        bars: list[HistoricalBar] = []
        for row in rows:
            stamp = _iso_timestamp(row.get("time") or row.get("date"))
            day_text = _date_text(row.get("time") or row.get("date"))
            if not stamp or not day_text:
                continue
            day = date.fromisoformat(day_text)
            # Some Vnstock explorers return a small warm-up prefix outside the requested
            # range. The terminal contract is strict: callers must never receive bars they
            # did not request, especially across a display-session boundary.
            if day < requested_start or day > requested_end:
                continue
            open_price = _raw_price(sym, row.get("open"), already_raw=False)
            high_price = _raw_price(sym, row.get("high"), already_raw=False)
            low_price = _raw_price(sym, row.get("low"), already_raw=False)
            close_price = _raw_price(sym, row.get("close"), already_raw=False)
            volume = _finite(row.get("volume"))
            if (
                volume is None or open_price is None or high_price is None
                or low_price is None or close_price is None
            ):
                continue
            if interval == "1D":
                complete = day <= completed_day
                bar_date = day_text
            else:
                opened = datetime.fromisoformat(stamp).astimezone(timezone.utc)
                minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1H": 60}.get(interval, 1)
                complete = intraday_bar_is_complete(opened, minutes, now_vn)
                bar_date = stamp
            price_basis = "ADJUSTED" if use_adjusted else "RAW"
            bars.append(HistoricalBar(
                date=bar_date,
                open=open_price, high=high_price, low=low_price, close=close_price,
                volume=volume,
                value=_finite(row.get("value") if row.get("value") is not None else row.get("va")),
                price_basis=price_basis,
                source=f"VNSTOCK_{source_name.upper()}",
                as_of=stamp,
                complete=complete,
                session_date=day_text,
                adjusted=use_adjusted,
            ))
        bars.sort(key=lambda bar: bar.date)
        return bars

    # -------------------------- profiles/fundamentals ------------------------
    async def _listing_rows(self) -> list[dict[str, Any]]:
        cached_at, rows = self._listing_cache
        if rows and time.monotonic() - cached_at < self._PROFILE_TTL:
            return rows
        rows = _records(await self._call("profiles", self._listing_fetcher))
        self._listing_cache = (time.monotonic(), rows)
        return rows

    async def get_stock_profiles(self, symbols: list[str]) -> list[dict[str, Any]]:
        wanted = {s.strip().upper() for s in symbols if s.strip()}
        rows = await self._listing_rows()
        result = []
        for row in rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            if symbol not in wanted:
                continue
            exchange = str(row.get("exchange") or "").strip().upper()
            result.append({
                "symbol": symbol,
                "name": row.get("organ_name"),
                "short_name": row.get("organ_short_name"),
                "exchange": "HOSE" if exchange == "HSX" else exchange or None,
                "source": "VNSTOCK_VCI",
            })
        return result

    async def _fundamental_rows(self, symbol: str) -> list[dict[str, Any]]:
        sym = symbol.strip().upper()
        cached = self._fundamental_cache.get(sym)
        if cached and time.monotonic() - cached[0] < self._FUNDAMENTAL_TTL:
            return cached[1]
        rows = _records(await self._call("fundamentals", self._fundamentals_fetcher, sym))
        rows.sort(key=lambda row: (_integer(row.get("year") or row.get("year_report")) or 0, _integer(row.get("quarter")) or 0))
        self._fundamental_cache[sym] = (time.monotonic(), rows)
        return rows

    async def get_stock_valuation(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for symbol in sorted({s.strip().upper() for s in symbols if s.strip()}):
            rows = await self._fundamental_rows(symbol)
            latest = rows[-1] if rows else {}
            year = _integer(latest.get("year") or latest.get("year_report"))
            quarter = _integer(latest.get("quarter"))
            result[symbol] = {
                "symbol": symbol,
                "pe": _finite(latest.get("pe")),
                "pb": _finite(latest.get("pb")),
                "as_of": f"{year}Q{quarter}" if year and quarter else None,
            }
        return result

    async def get_financial_ratios(self, symbol: str, quarters: int = 8) -> list[dict[str, Any]]:
        rows = (await self._fundamental_rows(symbol))[-max(1, quarters):]
        result = []
        for row in rows:
            year = _integer(row.get("year") or row.get("year_report"))
            quarter = _integer(row.get("quarter"))
            if not year or not quarter:
                continue
            result.append({
                "period": f"{year}Q{quarter}", "year": year, "quarter": quarter,
                "revenue": None, "net_profit": None,
                "ebit": _finite(row.get("ebit")),
                "net_margin": _finite(row.get("after_tax_profit_margin")),
                "roe": _finite(row.get("roe")), "roa": _finite(row.get("roa")),
                "roic": _finite(row.get("roic")),
                "gross_margin": _finite(row.get("gross_margin")),
            })
        return result

    # ------------------------------- overview --------------------------------
    async def _group_symbols(self, group: str) -> list[str]:
        cached = self._group_cache.get(group)
        if cached and time.monotonic() - cached[0] < self._PROFILE_TTL:
            return cached[1]
        value = await self._call(
            f"overview_group_{group.lower()}", self._group_fetcher, group
        )
        if hasattr(value, "tolist"):
            value = value.tolist()
        symbols = sorted({str(item).strip().upper() for item in (value or []) if str(item).strip()})
        self._group_cache[group] = (time.monotonic(), symbols)
        return symbols

    async def _safe_group_symbols(self, group: str) -> list[str]:
        try:
            return await self._group_symbols(group)
        except Exception as exc:  # noqa: BLE001 - component failure stays scoped
            logger.debug("Vnstock overview group %s unavailable: %s", group, type(exc).__name__)
            cached = self._group_cache.get(group)
            return list(cached[1]) if cached else []

    async def _safe_listing_rows(self) -> list[dict[str, Any]]:
        try:
            return await self._listing_rows()
        except Exception as exc:  # noqa: BLE001 - component failure stays scoped
            logger.debug("Vnstock overview listing unavailable: %s", type(exc).__name__)
            return list(self._listing_cache[1])

    async def _safe_index_history(
        self, symbol: str, start: str, end: str, interval: str
    ) -> list[dict[str, Any]]:
        scope = f"overview_index_{symbol.lower()}_{interval.lower()}"
        try:
            return _records(await self._call(
                scope, self._history_fetcher, symbol, "vci", start, end, interval
            ))
        except Exception as exc:  # noqa: BLE001 - one index cannot erase its peers
            logger.debug("Vnstock overview %s %s unavailable: %s", symbol, interval, type(exc).__name__)
            return []

    @staticmethod
    def _market_state(price: float | None, reference: float | None, ceiling: float | None, floor: float | None) -> str:
        if price is None:
            return "UNAVAILABLE"
        if ceiling is not None and math.isclose(price, ceiling):
            return "CEILING"
        if floor is not None and math.isclose(price, floor):
            return "FLOOR"
        if reference is not None and math.isclose(price, reference):
            return "REFERENCE"
        if reference is not None:
            return "UP" if price > reference else "DOWN"
        return "UNAVAILABLE"

    async def get_market_overview(self, cw_symbols: list[str]) -> dict[str, Any]:
        cached_at, cached = self._overview_cache
        if cached and time.monotonic() - cached_at < self._OVERVIEW_TTL:
            return cached
        session = reference_session_date().isoformat()
        phase = market_session.get_market_phase().value
        reference_only = phase == "PRE_OPEN"
        index_symbols = ["VN30", "VNINDEX", "VNFINLEAD", "VNDIAMOND"]
        groups = {
            "VN30": await self._safe_group_symbols("VN30"),
            "VNINDEX": [str(row.get("symbol")).upper() for row in await self._safe_listing_rows()
                        if str(row.get("exchange") or "").upper() == "HSX" and str(row.get("type") or "").upper() == "STOCK"],
            "VNFINLEAD": await self._safe_group_symbols("VNFINLEAD"),
            "VNDIAMOND": await self._safe_group_symbols("VNDIAMOND"),
        }
        board_symbols = sorted(set(groups["VNINDEX"]) | {s.upper() for s in cw_symbols})
        try:
            board = await self._board_rows(board_symbols, "overview_board")
        except Exception as exc:  # noqa: BLE001 - index cards can still be returned
            logger.debug("Vnstock overview board unavailable: %s", type(exc).__name__)
            board = {}

        def valid_row(symbol: str) -> dict[str, Any] | None:
            row = board.get(symbol)
            return row if row and _date_text(row.get("TD") or row.get("trading_date")) == session else None

        def leaders(symbols: list[str]) -> list[dict[str, Any]]:
            values = []
            for symbol in symbols:
                row = valid_row(symbol)
                if row is None:
                    continue
                volume = _finite(row.get("volume_accumulated"))
                # A zero-volume board row is only a pre-open placeholder. Ranking it
                # fabricated a top-five table from whichever zero happened to arrive
                # first and made an empty new session look active.
                if volume is None or volume <= 0:
                    continue
                price, ref = _finite(row.get("close_price")), _finite(row.get("reference_price"))
                if price is not None and price <= 0:
                    price = None
                ceiling, floor = _finite(row.get("ceiling_price")), _finite(row.get("floor_price"))
                values.append({
                    "symbol": symbol, "volume": volume, "price": price, "reference": ref,
                    "ceiling": ceiling, "floor": floor,
                    "market_state": self._market_state(price, ref, ceiling, floor),
                    "as_of": _iso_timestamp(row.get("time"), session_date=session),
                    "session_date": session,
                    "provenance": {
                        "price": {"source": "VNSTOCK_KBS_PRICE_BOARD", "session_date": session},
                        "volume": {"source": "VNSTOCK_KBS_PRICE_BOARD", "session_date": session},
                        "bands": {"source": "VNSTOCK_KBS_PRICE_BOARD", "session_date": session},
                    },
                })
            return sorted(values, key=lambda item: item["volume"], reverse=True)[:5]

        indices = []
        start = (date.fromisoformat(session) - timedelta(days=7)).isoformat()
        for symbol in index_symbols:
            daily_rows = await self._safe_index_history(symbol, start, session, "1D")
            intraday_rows = await self._safe_index_history(symbol, session, session, "5m")
            daily: list[tuple[dict[str, Any], str]] = []
            for row in daily_rows:
                day = _date_text(row.get("time"))
                if day is not None:
                    daily.append((row, day))
            daily.sort(key=lambda item: item[1])
            current = next((r for r, day in reversed(daily) if day == session), None)
            previous = next((r for r, day in reversed(daily) if day < session), None)
            price = None if reference_only else _finite((current or {}).get("close"))
            if price is not None and price <= 0:
                price = None
            reference = _finite((previous or {}).get("close"))
            change = price - reference if price is not None and reference is not None else None
            members = [] if reference_only else [valid_row(member) for member in groups[symbol]]
            members = [row for row in members if row is not None]
            states = [self._market_state(_finite(r.get("close_price")), _finite(r.get("reference_price")), _finite(r.get("ceiling_price")), _finite(r.get("floor_price"))) for r in members]
            sparkline = []
            for row in ([] if reference_only else intraday_rows):
                if _date_text(row.get("time")) != session:
                    continue
                point_stamp = _iso_timestamp(row.get("time"))
                point_value = _finite(row.get("close"))
                if point_stamp and point_value is not None:
                    sparkline.append({"timestamp": point_stamp, "value": point_value, "reference": reference, "volume": _finite(row.get("volume"))})
            as_of = sparkline[-1]["timestamp"] if sparkline else (
                None if reference_only else _iso_timestamp((current or {}).get("time"))
            )
            expected_members = len(groups[symbol])
            breadth_coverage = len(members) / expected_members if expected_members else 0.0
            has_breadth = bool(members)
            complete_breadth = bool(expected_members and len(members) == expected_members)
            availability = (
                "AVAILABLE" if price is not None and sparkline and complete_breadth
                else "PARTIAL" if price is not None or reference is not None or has_breadth else "UNAVAILABLE"
            )
            advancing = None if reference_only else states.count("UP")
            ceiling_count = None if reference_only else states.count("CEILING")
            unchanged = None if reference_only else states.count("REFERENCE")
            declining = None if reference_only else states.count("DOWN")
            floor_count = None if reference_only else states.count("FLOOR")
            indices.append({
                "symbol": symbol, "value": price, "change": change,
                "change_percent": change / reference * 100 if change is not None and reference else None,
                "reference": reference,
                "volume": None if reference_only else _finite((current or {}).get("volume")),
                "trading_value": None if reference_only else _finite((current or {}).get("value") or (current or {}).get("va")),
                "advancing": advancing, "ceiling": ceiling_count,
                "unchanged": unchanged, "declining": declining,
                "floor": floor_count, "as_of": as_of, "session_date": session,
                "breadth_observed": len(members), "breadth_expected": expected_members,
                "breadth_coverage": breadth_coverage,
                "update_mode": "POLLED", "sparkline": sparkline, "availability": availability,
                "partial_reasons": (["PRE_OPEN_REFERENCE_ONLY"] if reference_only else []) + [reason for reason, missing in (
                    ("PRICE_UNAVAILABLE", price is None), ("REFERENCE_UNAVAILABLE", reference is None),
                    ("INTRADAY_UNAVAILABLE", not sparkline),
                    ("BREADTH_UNAVAILABLE", not has_breadth),
                    ("BREADTH_PARTIAL", has_breadth and not complete_breadth),
                ) if missing],
                "provenance": {
                    "price": {"source": "VNSTOCK_VCI", "as_of": as_of, "session_date": session},
                    "reference": {"source": "VNSTOCK_VCI_PRIOR_CLOSE", "as_of": None,
                                  "session_date": session,
                                  "observed_session_date": max((day for _, day in daily if day < session), default=None)},
                    "totals": {"source": "VNSTOCK_VCI", "as_of": as_of, "session_date": session,
                               "availability": "UNAVAILABLE" if reference_only else "AVAILABLE" if current else "UNAVAILABLE"},
                    "breadth": {"source": "DERIVED_VNSTOCK_KBS_CONSTITUENTS", "as_of": as_of,
                                "session_date": session,
                                "availability": "AVAILABLE" if complete_breadth else "PARTIAL" if has_breadth else "UNAVAILABLE",
                                "observed": len(members), "expected": expected_members},
                    "sparkline": {"source": "VNSTOCK_VCI", "as_of": as_of, "session_date": session,
                                  "timeframe": "5m", "availability": "AVAILABLE" if sparkline else "UNAVAILABLE"},
                },
            })
        stock_leaders = leaders(groups["VNINDEX"])
        cw_leaders = leaders([s.upper() for s in cw_symbols])
        useful = bool(stock_leaders or cw_leaders or any(i["availability"] != "UNAVAILABLE" for i in indices))
        availability = (
            "AVAILABLE" if all(i["availability"] == "AVAILABLE" for i in indices) and stock_leaders and cw_leaders
            else "PARTIAL" if useful else "UNAVAILABLE"
        )
        valid_board_rows = [row for symbol in board_symbols if (row := valid_row(symbol)) is not None]
        bands_available = bool(valid_board_rows) and all(
            _finite(row.get("ceiling_price")) is not None and _finite(row.get("floor_price")) is not None
            for row in valid_board_rows
        )
        result = {
            "display_session": session, "indices": indices,
            "top_stock_volume": stock_leaders, "top_cw_volume": cw_leaders,
            "as_of": max((i.get("as_of") for i in indices if i.get("as_of")), default=None),
            "market_session_active": market_session.is_trading_active(),
            "market_phase": phase,
            "stock_scope": "HOSE (VNINDEX constituents)", "cw_scope": "active CW registry",
            "source": "VNSTOCK", "availability": availability,
            "components": {
                "indices": "AVAILABLE" if all(i["value"] is not None for i in indices) else "PARTIAL",
                "top_stock_volume": "AVAILABLE" if stock_leaders else "UNAVAILABLE",
                "top_cw_volume": "AVAILABLE" if cw_leaders else "UNAVAILABLE",
                "breadth": "AVAILABLE" if all(i["provenance"]["breadth"]["availability"] == "AVAILABLE" for i in indices) else "PARTIAL",
                "bands": "AVAILABLE" if bands_available else "PARTIAL" if valid_board_rows else "UNAVAILABLE",
            },
        }
        self._overview_cache = (time.monotonic(), result)
        return result

    # -------------------------------- health ---------------------------------
    @staticmethod
    def _ms_iso(value: int | None) -> str | None:
        return datetime.fromtimestamp(value / 1000.0, timezone.utc).isoformat() if value else None

    def get_health(self) -> dict[str, Any]:
        active = market_session.is_trading_active()
        display_session = reference_session_date().isoformat()
        check_age = (
            max(0.0, time.monotonic() - self._last_board_check_monotonic)
            if self._last_board_check_monotonic is not None else None
        )
        pollers_running = bool(
            self._connected and self._active_symbols and self._quote_task and not self._quote_task.done()
        )
        current_session_data = self._last_data_session == display_session
        fresh = bool(
            active and pollers_running and current_session_data
            and check_age is not None and check_age <= self._freshness
        )
        upstream = (
            "UNAVAILABLE" if not self._enabled else "DISCONNECTED" if not self._connected
            else "READY" if not self._active_symbols or not active
            else "LIVE" if fresh else "STALE" if current_session_data else "CONNECTING"
        )
        last_data = self._ms_iso(self._last_data_at_ms)
        return {
            "feedStatus": self._access.wire(
                fresh=fresh,
                active=active,
                last_data_at=last_data if current_session_data else None,
            ),
            "provider": "vnstock", "source": "VNSTOCK_KBS_VCI",
            "transport_mode": "POLLING", "access_tier": "UNVERIFIED",
            "api_key_configured": self._api_key_present, "license_verified": None,
            # Public Vnstock datasets do not establish a login session. Keep the legacy
            # field false instead of equating "a key file exists" with authentication.
            "authenticated": False, "upstream_status": upstream,
            "trade_stream_connected": pollers_running, "bid_ask_stream_connected": pollers_running,
            "subscription_count": len(self._active_symbols), "max_subscriptions": self.max_symbols,
            "subscriptions": self.get_active_subscriptions(), "feed_fresh": fresh,
            "feed_freshness_seconds": self._freshness, "latest_tick_age_seconds": check_age,
            "trade_tick_age_seconds": (
                max(0.0, time.time() - self._last_trade_at_ms / 1000.0) if self._last_trade_at_ms else None
            ),
            "book_tick_age_seconds": (
                max(0.0, time.time() - self._last_book_at_ms / 1000.0) if self._last_book_at_ms else None
            ),
            "last_trade_tick_at": self._ms_iso(self._last_trade_at_ms),
            "last_book_tick_at": self._ms_iso(self._last_book_at_ms), "last_tick_at": last_data,
            "last_error": self._last_error_code, "request_count": self._request_count,
            "request_failure_count": self._request_failures,
            "quote_poll_seconds": self._quote_interval, "tape_sweep_seconds": self._tape_sweep,
            "min_request_interval_seconds": self._request_floor,
            "reconnect_count": 0, "silent_stream_reconnect_count": 0,
            "stream_watchdog_active": False, "stream_silence_reconnect_seconds": 0.0,
            "signalr_decode_error_count": 0,
        }
