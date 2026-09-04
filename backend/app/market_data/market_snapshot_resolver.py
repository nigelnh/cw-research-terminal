"""After-hours / crash-safe market row resolver (Step 13C).

For each requested symbol, produce one fully-resolved dashboard row using an explicit,
field-group precedence:

  A. LIVE               - active session + a fresh MarketState tick
  B. LAST_SESSION        - instrument_snapshots row for the last completed session
                           (the only source of a closing bid/ask)
  C. HISTORICAL / EOD    - market_bars daily close/OHLC/volume for the symbol's latest
                           session; reference = previous session's close; change = derived.
                           One controlled gap-fill for a missing latest-session bar.
  D. UNAVAILABLE         - realtime-only fields (bid/ask/spread) with no B source

The row is emitted in the same wire shape the WS ``snapshots`` frame uses (so the frontend
mappers are reused) plus a compact ``provenance`` block and a row-level ``displayState``.
Prices are scaled to the gateway "thousand-VND" transport exactly like
``CanonicalQuote.to_wire_snapshot_row``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from time import monotonic
from typing import Any, Optional
from weakref import WeakValueDictionary

from app.core.config import settings
from app.market_data import trading_calendar as cal
from app.market_data.market_schemas import HistoricalBar
from app.market_data.market_session import market_session
from app.market_data.session_reference import reference_session_date
from app.market_data.market_state import market_state
from app.market_data.temporal import (
    DataSource,
    DataTemporalState,
    FieldProvenance,
    derive_display_state,
)

logger = logging.getLogger(__name__)

_QUOTE_FIELDS = (
    "reference_price", "ceiling_price", "floor_price",
    "last_price", "price_change", "price_change_percent",
    "open_price", "high_price", "low_price", "average_price",
    "total_volume", "trading_value", "traded_quantity", "underlying_price",
)
_BOOK_FIELDS = (
    "bid1_price", "bid1_quantity", "ask1_price", "ask1_quantity",
    "bid2_price", "bid2_quantity", "ask2_price", "ask2_quantity",
    "bid3_price", "bid3_quantity", "ask3_price", "ask3_quantity",
)


@dataclass
class ResolvedRow:
    symbol: str
    instrument_type: str
    values: dict[str, Optional[float]] = field(default_factory=dict)  # RAW VND / points
    underlying_symbol: Optional[str] = None
    analytics: Optional[dict[str, Any]] = None
    quote_prov: FieldProvenance = field(
        default_factory=lambda: FieldProvenance(DataTemporalState.UNAVAILABLE, DataSource.NONE)
    )
    book_prov: FieldProvenance = field(
        default_factory=lambda: FieldProvenance(DataTemporalState.UNAVAILABLE, DataSource.NONE)
    )
    reference_prov: FieldProvenance = field(
        default_factory=lambda: FieldProvenance(DataTemporalState.UNAVAILABLE, DataSource.NONE)
    )
    analytics_prov: Optional[FieldProvenance] = None
    is_realtime_eligible: bool = False
    diag: dict[str, Any] = field(default_factory=dict)

    # -- wire --------------------------------------------------------- #
    def to_wire(self) -> dict[str, Any]:
        is_index = self.instrument_type == "INDEX"
        scale = 1.0 if is_index else 1000.0

        def p(key: str) -> Optional[float]:
            v = self.values.get(key)
            return None if v is None else round(v / scale, 6)

        v = self.values
        b, a = v.get("bid1_price"), v.get("ask1_price")
        spread = spread_pct = None
        if b is not None and a is not None and a >= b:
            spread = a - b
            if a + b > 0:
                spread_pct = round((a - b) / ((a + b) / 2.0) * 100.0, 4)

        groups = [g for g in (self.quote_prov, self.book_prov, self.analytics_prov) if g is not None]
        row: dict[str, Any] = {
            "Symbol": self.symbol,
            "InstrumentType": self.instrument_type,
            "Ref": p("reference_price"),
            "Ceil": p("ceiling_price"),
            "Floor": p("floor_price"),
            "Traded": p("last_price"),
            "change": p("price_change"),
            "ChangePercent": v.get("price_change_percent"),
            "Open_Prc": p("open_price"),
            "High_Prc": p("high_price"),
            "Low_Prc": p("low_price"),
            "Avg_Prc": p("average_price"),
            "Total_Vol": v.get("total_volume"),
            "Traded_Qty": v.get("traded_quantity"),
            "Trading_Val": p("trading_value"),
            "Bid1_Prc": p("bid1_price"), "Bid1_Qty": v.get("bid1_quantity"),
            "Ask1_Prc": p("ask1_price"), "Ask1_Qty": v.get("ask1_quantity"),
            "Bid2_Prc": p("bid2_price"), "Bid2_Qty": v.get("bid2_quantity"),
            "Ask2_Prc": p("ask2_price"), "Ask2_Qty": v.get("ask2_quantity"),
            "Bid3_Prc": p("bid3_price"), "Bid3_Qty": v.get("bid3_quantity"),
            "Ask3_Prc": p("ask3_price"), "Ask3_Qty": v.get("ask3_quantity"),
            "Spread": None if spread is None else round(spread / scale, 6),
            "SpreadPercent": spread_pct,
            "Under_Symbol": self.underlying_symbol,
            "Under_Prc": p("underlying_price"),
            "is_realtime_eligible": self.is_realtime_eligible,
            "displayState": derive_display_state(groups).value,
            "provenance": {
                "quote": self.quote_prov.to_wire(),
                "book": self.book_prov.to_wire(),
                "reference": self.reference_prov.to_wire(),
                **({"analytics": self.analytics_prov.to_wire()} if self.analytics_prov else {}),
            },
        }
        if self.analytics is not None:
            row["analytics"] = self.analytics
        if self.diag:
            row["_diag"] = self.diag
        return row


class MarketSnapshotResolver:
    def __init__(self, sessionmaker=None) -> None:
        self._sm = sessionmaker  # async_sessionmaker | None
        self._store = None
        self._history_cache: dict[tuple[str, str, str], tuple[float, list[HistoricalBar]]] = {}
        self._history_locks: WeakValueDictionary[tuple[str, str, str], asyncio.Lock] = WeakValueDictionary()

    def configure(self, sessionmaker, *, store=None) -> None:
        self._sm = sessionmaker
        self._store = store
        self._history_cache.clear()
        self._history_locks.clear()

    async def resolve_rows(
        self,
        symbols: list[str],
        *,
        now: Optional[datetime] = None,
        diag: bool = False,
        enrich_snapshot_history: bool = True,
    ) -> list[ResolvedRow]:
        now = now or datetime.now(cal.VN_TZ)
        clean = list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))
        latest_session = cal.latest_completed_trading_session(now)
        session_active = cal.is_trading_active(now)

        # Batch-load snapshots + registry underlyings once.
        snapshots = await self._load_snapshots(clean)
        # A slow history fallback for one symbol must not hold every other ready snapshot
        # behind it.  ``gather`` preserves input order while the DB/provider gates bound the
        # actual I/O concurrency.
        rows = await asyncio.gather(
            *(
                self._resolve_one(
                    sym, now=now, latest_session=latest_session,
                    session_active=session_active, snapshot=snapshots.get(sym), diag=diag,
                    enrich_snapshot_history=enrich_snapshot_history,
                )
                for sym in clean
            )
        )
        return rows

    async def resolve_analytics_rows(
        self, symbols: list[str], *, now: Optional[datetime] = None
    ) -> list[dict[str, Any]]:
        """Resolve CW analytics independently from price snapshots.

        Dashboard quotes are the critical reload path and must never wait for EOD quant
        database reads.  This companion read is deliberately parallel and can complete
        later; the frontend merges rows by symbol without blanking already-rendered prices.
        """
        now = now or datetime.now(cal.VN_TZ)
        clean = list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))
        latest_session = cal.latest_completed_trading_session(now)
        session_active = cal.is_trading_active(now)
        rows = [
            ResolvedRow(symbol=sym, instrument_type="CW")
            for sym in clean
            if market_state._determine_instrument_type(sym) == "CW"
        ]
        await asyncio.gather(
            *(
                self._attach_analytics(
                    row,
                    row.symbol,
                    now=now,
                    latest_session=latest_session,
                    session_active=session_active,
                )
                for row in rows
            )
        )
        return [
            {
                "Symbol": row.symbol,
                "analytics": row.analytics,
                "provenance": (
                    row.analytics_prov.to_wire()
                    if row.analytics_prov is not None
                    else FieldProvenance(
                        DataTemporalState.UNAVAILABLE,
                        DataSource.NONE,
                        note="analytics unavailable",
                    ).to_wire()
                ),
            }
            for row in rows
        ]

    # ------------------------------------------------------------------ #
    async def _load_snapshots(self, symbols: list[str]) -> dict:
        if not self._sm or not symbols or not settings.SNAPSHOT_ENABLED:
            return {}
        try:
            from app.persistence.repositories.snapshot_repository import SnapshotRepository

            async with self._sm() as session:
                return await SnapshotRepository(session).get_many_latest(symbols)
        except Exception as e:  # noqa: BLE001
            logger.warning("snapshot batch load failed: %s", e)
            return {}

    async def _resolve_one(
        self, sym: str, *, now: datetime, latest_session: date, session_active: bool,
        snapshot, diag: bool, enrich_snapshot_history: bool,
    ) -> ResolvedRow:
        inst_type = market_state._determine_instrument_type(sym)
        row = ResolvedRow(symbol=sym, instrument_type=inst_type)
        trace: list[str] = []

        # ---- A. LIVE ------------------------------------------------- #
        live = market_state.get_quote(sym)
        live_sd = market_state._quote_market_session_date(live) if live is not None else None
        display_session = reference_session_date(now)
        new_session_pending = display_session > latest_session
        memory_ok = (
            live is not None and live_sd is not None
            and live_sd <= now.date().isoformat()
            and live_sd >= latest_session.isoformat()
            and (not new_session_pending or live_sd == display_session.isoformat())
            and (snapshot is None or live_sd >= snapshot.session_date.isoformat())
            and cal.is_trading_day(date.fromisoformat(live_sd))
            and any(
                getattr(live, f, None) is not None and getattr(live, f) > 0
                for f in ("last_price", "bid1_price", "ask1_price")
            )
        )
        if memory_ok and live is not None:
            row.instrument_type = live.instrument_type or inst_type
            for f in _QUOTE_FIELDS:
                row.values[f] = getattr(live, f, None)
            for f in _BOOK_FIELDS:
                row.values[f] = getattr(live, f, None)
            row.underlying_symbol = live.underlying_symbol
            sd = live_sd
            def group_provenance(ts, received, has_value):
                if not has_value:
                    return FieldProvenance(DataTemporalState.UNAVAILABLE, DataSource.NONE,
                                           note="no observation for this group in this session")
                fresh = (sd == now.date().isoformat() and session_active
                         and market_session.is_display_eligible(ts, now, max_age_seconds=180)
                         and market_session.is_display_eligible(received, now, max_age_seconds=180))
                state = DataTemporalState.LIVE if fresh else (
                    DataTemporalState.SESSION_SNAPSHOT if sd > latest_session.isoformat()
                    else DataTemporalState.LAST_SESSION)
                return FieldProvenance(state, DataSource.LIVE_FEED, _iso_ms(ts), sd,
                                       stale=bool(session_active and not fresh),
                                       note=None if ts else "observation timestamp unavailable")
            row.quote_prov = group_provenance(
                live.trade_timestamp or live.source_timestamp or live.received_timestamp,
                live.trade_received_timestamp or live.received_timestamp,
                live.last_price is not None)
            row.book_prov = group_provenance(
                live.book_timestamp or (live.source_timestamp if live.trade_timestamp is None else None),
                live.book_received_timestamp or (live.received_timestamp if live.book_timestamp is None else None),
                any(getattr(live, f) is not None for f in _BOOK_FIELDS))
            row.is_realtime_eligible = any(g.state == DataTemporalState.LIVE for g in (row.quote_prov, row.book_prov))
            trace.append("A:MEMORY_GROUPS")
            if live.reference_session_date == sd and any(
                row.values.get(field) is not None
                for field in ("reference_price", "ceiling_price", "floor_price")
            ):
                row.reference_prov = FieldProvenance(
                    DataTemporalState.DERIVED,
                    DataSource.SESSION_REFERENCE,
                    _iso_ms(live.reference_timestamp),
                    sd,
                )
                trace.append("A:SESSION_REFERENCE")
            else:
                # Never carry a previous session's bands into a current live row.
                row.values["reference_price"] = None
                row.values["ceiling_price"] = None
                row.values["floor_price"] = None
            if row.values.get("reference_price") is None and sd == now.date().isoformat() and sd > latest_session.isoformat():
                await self._fill_live_reference(
                    row, sym, inst_type=inst_type, snapshot=snapshot,
                    latest_session=latest_session, now=now, trace=trace,
                )
            if diag:
                row.diag = {"chosen": "LIVE", "trace": trace}
            return row

        # At 08:00 stop exposing yesterday's trade/book as today's values. A current
        # checkpoint may still hydrate the new session after a restart; otherwise wait
        # for real observations (including book-only ATO), with independently dated bands.
        if new_session_pending and (snapshot is None or snapshot.session_date < display_session):
            self._overlay_current_reference(row, live, now=now, trace=trace)
            row.quote_prov = FieldProvenance(
                DataTemporalState.UNAVAILABLE, DataSource.NONE, session_date=display_session.isoformat(),
                note="awaiting a trade in the new session (08:00 ICT rollover)")
            row.book_prov = FieldProvenance(
                DataTemporalState.UNAVAILABLE, DataSource.NONE, session_date=display_session.isoformat(),
                note="awaiting an order book in the new session")
            if diag:
                row.diag = {"chosen": "AWAITING_SESSION", "trace": trace}
            return row

        # ---- B. LAST_SESSION snapshot ------------------------------- #
        snapshot_complete = False
        if snapshot is not None and snapshot.session_date <= now.date():
            snap_session = snapshot.session_date
            snap_stale = snap_session < latest_session
            trade_ts = getattr(snapshot, "trade_timestamp", None)
            book_ts = getattr(snapshot, "book_timestamp", None)
            as_of = trade_ts.isoformat() if trade_ts else None
            sd = snap_session.isoformat()
            state = (DataTemporalState.SESSION_SNAPSHOT if snap_session > latest_session
                     else DataTemporalState.HISTORICAL if snap_stale else DataTemporalState.LAST_SESSION)
            for f in _QUOTE_FIELDS:
                row.values[f] = _num(getattr(snapshot, f, None))
            row.underlying_symbol = snapshot.underlying_symbol
            src = (
                DataSource.SNAPSHOT_FINAL if snapshot.quality == "FINAL"
                else DataSource.SNAPSHOT_SEED if snapshot.quality == "SEED"
                else DataSource.SNAPSHOT_CHECKPOINT
            )
            row.quote_prov = FieldProvenance(
                state,
                src, as_of, sd, stale=snap_stale,
            )
            if row.values.get("last_price") is None:
                row.quote_prov = FieldProvenance(
                    DataTemporalState.UNAVAILABLE,
                    DataSource.NONE,
                    note="snapshot has no observed trade price",
                )
            if row.values.get("reference_price") is not None:
                row.reference_prov = row.quote_prov
            # Book only from a real observed snapshot (not the EOD seed).
            has_book = snapshot.quality != "SEED" and (
                _num(snapshot.bid1_price) is not None or _num(snapshot.ask1_price) is not None
            )
            if has_book:
                for f in _BOOK_FIELDS:
                    row.values[f] = _num(getattr(snapshot, f, None))
                row.book_prov = FieldProvenance(
                    state,
                    src, book_ts.isoformat() if book_ts else None, sd, stale=snap_stale,
                )
            else:
                row.book_prov = FieldProvenance(
                    DataTemporalState.UNAVAILABLE, DataSource.NONE, note="no closing order book recorded",
                )
            trace.append(f"B:SNAPSHOT({snapshot.quality})")
            # A present close alone does not make the snapshot complete. Preserve its
            # observed fields while filling any OHLC/reference gaps from daily bars.
            history_fields = (
                "last_price", "open_price", "high_price", "low_price",
                "total_volume", "reference_price", "price_change", "price_change_percent",
            )
            snapshot_complete = not snap_stale and all(
                row.values.get(f) is not None for f in history_fields
            )

        # A persisted closing snapshot owns last trade/OHLC/book outside the live
        # session, while the canonical in-memory state owns the static bands for the
        # current display session. Overlay only those three fields so a closed-session
        # row can still classify its prices without exposing stale intraday data.
        self._overlay_current_reference(row, live, now=now, trace=trace)
        # The dashboard reload path prefers an observed persisted snapshot immediately.
        # Missing optional OHLC/reference fields remain null with truthful provenance;
        # they must not turn a ready quote into a multi-second history dependency.
        if (
            snapshot is not None
            and not enrich_snapshot_history
            and row.values.get("last_price") is not None
        ):
            if diag:
                row.diag = {"chosen": "SNAPSHOT_FAST", "trace": trace}
            return row
        if snapshot_complete or (snapshot is not None and snapshot.session_date > latest_session):
            if diag:
                row.diag = {"chosen": "SNAPSHOT", "trace": trace}
            return row

        # ---- C. HISTORICAL / EOD bars ------------------------------ #
        bars = await self._recent_daily_bars(sym, inst_type, now=now)
        bars = [b for b in bars if (_parse_date(b.date) or now.date()) <= latest_session]
        if bars:
            target_session = row.quote_prov.session_date
            eligible_bars = ([b for b in bars if _parse_date(b.date).isoformat() <= target_session]
                             if target_session else bars)
            if not eligible_bars:
                eligible_bars = bars
            last_bar = eligible_bars[-1]
            prev_close = eligible_bars[-2].close if len(eligible_bars) >= 2 else None
            bar_session = _parse_date(last_bar.date)
            bar_stale = bar_session is not None and bar_session < latest_session
            sd = bar_session.isoformat() if bar_session else None
            as_of = f"{sd}T15:00:00+07:00" if sd else None


            # Only fill fields the snapshot didn't already provide.
            def _fill(key: str, value: Optional[float]) -> None:
                if row.values.get(key) is None:
                    row.values[key] = value
            _fill("last_price", last_bar.close)
            _fill("open_price", last_bar.open)
            _fill("high_price", last_bar.high)
            _fill("low_price", last_bar.low)
            _fill("total_volume", int(last_bar.volume) if last_bar.volume is not None else None)
            _fill("trading_value", last_bar.value)
            if row.values.get("reference_price") is None:
                _fill("reference_price", prev_close)
                if prev_close is not None:
                    prev_session = _parse_date(bars[-2].date)
                    ref_as_of = (
                        f"{prev_session.isoformat()}T15:00:00+07:00"
                        if prev_session else None
                    )
                    row.reference_prov = FieldProvenance(
                        DataTemporalState.LAST_SESSION if not bar_stale else DataTemporalState.HISTORICAL,
                        DataSource.PRIOR_CLOSE,
                        ref_as_of,
                        sd,
                        stale=bool(bar_stale),
                    )
            resolved_close = row.values.get("last_price")
            resolved_reference = row.values.get("reference_price")
            if (resolved_close is not None and resolved_reference not in (None, 0)
                    and row.reference_prov.session_date == sd):
                if row.values.get("price_change") is None:
                    row.values["price_change"] = round(resolved_close - resolved_reference, 4)
                if row.values.get("price_change_percent") is None:
                    row.values["price_change_percent"] = round(
                        (resolved_close - resolved_reference) / resolved_reference, 6
                    )

            state = DataTemporalState.LAST_SESSION if not bar_stale else DataTemporalState.HISTORICAL
            if row.quote_prov.state == DataTemporalState.UNAVAILABLE:
                row.quote_prov = FieldProvenance(state, DataSource.EOD_BARS, as_of, sd, stale=bool(bar_stale))
            trace.append(f"C:EOD_BARS(n={len(bars)})")
            if diag:
                row.diag = {
                    "chosen": "EOD_BARS" if row.quote_prov.source == DataSource.EOD_BARS else row.quote_prov.source.value,
                    "trace": trace, "bar_session": sd, "latest_session": latest_session.isoformat(),
                }
            return row

        # ---- D. nothing ------------------------------------------- #
        if row.quote_prov.state == DataTemporalState.UNAVAILABLE:
            row.quote_prov = FieldProvenance(
                DataTemporalState.UNAVAILABLE, DataSource.NONE,
                note="no live tick, no persisted snapshot, no daily history",
            )
        trace.append("D:UNAVAILABLE")
        if diag:
            row.diag = {"chosen": "UNAVAILABLE", "trace": trace}
        return row

    @staticmethod
    def _overlay_current_reference(
        row: ResolvedRow,
        live,
        *,
        now: datetime,
        trace: list[str],
    ) -> None:
        if live is None:
            return
        session_date = reference_session_date(now).isoformat()
        if live.reference_session_date != session_date:
            return
        values = {
            "reference_price": live.reference_price,
            "ceiling_price": live.ceiling_price,
            "floor_price": live.floor_price,
        }
        if not any(value is not None for value in values.values()):
            return
        for field, value in values.items():
            if value is not None:
                row.values[field] = value
        row.reference_prov = FieldProvenance(
            DataTemporalState.DERIVED,
            DataSource.SESSION_REFERENCE,
            _iso_ms(live.reference_timestamp),
            session_date,
        )
        trace.append("A:SESSION_REFERENCE_STATIC")

    async def _fill_live_reference(
        self,
        row: ResolvedRow,
        sym: str,
        *,
        inst_type: str,
        snapshot,
        latest_session: date,
        now: datetime,
        trace: list[str],
    ) -> None:
        """Fill only today's reference price; session bands are never inferred."""
        if row.values.get("reference_price") is not None:
            return
        reference = None
        as_of = None
        if snapshot is not None and snapshot.session_date == latest_session:
            reference = _num(snapshot.last_price)
            as_of = snapshot.captured_at.isoformat() if snapshot.captured_at else None
            if reference is not None:
                trace.append("B:PRIOR_CLOSE_SNAPSHOT")
        if reference is None:
            bars = await self._recent_daily_bars(sym, inst_type, now=now)
            eligible = [bar for bar in bars if (_parse_date(bar.date) or latest_session) <= latest_session]
            if eligible:
                latest = eligible[-1]
                reference = latest.close
                session = _parse_date(latest.date)
                as_of = f"{session.isoformat()}T15:00:00+07:00" if session else None
                trace.append("C:PRIOR_CLOSE_EOD")
        if reference is not None:
            row.values["reference_price"] = reference
            row.reference_prov = FieldProvenance(
                DataTemporalState.DERIVED,
                DataSource.PRIOR_CLOSE,
                as_of,
                now.date().isoformat(),
            )
        else:
            row.reference_prov = FieldProvenance(
                DataTemporalState.UNAVAILABLE,
                DataSource.NONE,
                note="current-session reference metadata unavailable",
            )

    async def _attach_analytics(
        self, row: ResolvedRow, sym: str, *, now: datetime, latest_session: date, session_active: bool
    ) -> None:
        from app.quant.quant_engine import live_quant_engine

        # Live analytics while the session is active and the engine has a fresh value.
        if session_active:
            live = live_quant_engine.get_analytics(sym)
            if live is not None and live.is_available:
                row.analytics = _analytics_wire(live)
                row.analytics_prov = FieldProvenance(
                    DataTemporalState.LIVE, DataSource.QUANT_LIVE,
                    as_of=live.calculated_at, session_date=now.date().isoformat(),
                )
                return

        # EOD analytics for the last completed session (temporally aligned inputs).
        try:
            eod = await live_quant_engine.compute_eod_analytics(
                sym, latest_session, sessionmaker=self._sm
            )
        except Exception as e:  # noqa: BLE001
            logger.info("resolver: EOD analytics for %s failed: %s", sym, e)
            row.analytics_prov = FieldProvenance(
                DataTemporalState.UNAVAILABLE,
                DataSource.NONE,
                note="EOD analytics temporarily unavailable",
            )
            return
        if eod is not None and eod.is_available:
            row.analytics = _analytics_wire(eod)
            row.analytics_prov = FieldProvenance(
                DataTemporalState.LAST_SESSION, DataSource.QUANT_EOD,
                as_of=eod.calculated_at, session_date=latest_session.isoformat(),
            )
        else:
            row.analytics_prov = FieldProvenance(
                DataTemporalState.UNAVAILABLE, DataSource.NONE,
                note=(eod.unavailable_reason if eod is not None else "no EOD analytics"),
            )

    async def _recent_daily_bars(
        self, sym: str, inst_type: str, *, now: datetime | None = None
    ) -> list[HistoricalBar]:
        """Session-scoped L1/Redis fallback cache, separate from live quote state.

        Incomplete legacy snapshots may need an actual historical close. Those reads must
        not hit FiinQuant again on every reload or after a backend restart. Never cache a
        future/current incomplete session under the last-completed-session key.
        """
        now = now or datetime.now(cal.VN_TZ)
        latest_session = cal.latest_completed_trading_session(now).isoformat()
        basis = "RAW" if inst_type == "CW" else "ADJUSTED"
        key = (sym, basis, latest_session)
        cached = self._history_cache.get(key)
        if cached is not None and cached[0] > monotonic():
            return cached[1]
        lock = self._history_locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._history_cache.get(key)
            if cached is not None and cached[0] > monotonic():
                return cached[1]
            bars = None
            if self._store is not None:
                bars = await self._store.load_dashboard_history(sym, basis, latest_session)
            if bars is None:
                fetched = await self._fetch_recent_daily_bars(sym, inst_type, now=now)
                bars = [
                    bar.model_copy(update={
                        "price_basis": basis,
                        "adjusted": basis == "ADJUSTED",
                        "session_date": bar.session_date or bar.date[:10],
                    })
                    for bar in fetched
                    if bar.price_basis in (None, basis)
                    and (bar.session_date or bar.date[:10]) <= latest_session
                ]
                if bars and self._store is not None:
                    await self._store.save_dashboard_history(sym, basis, latest_session, bars)
            ttl = settings.DASHBOARD_HISTORY_CACHE_TTL_SECONDS if bars else 30
            if len(self._history_cache) >= 512:
                self._history_cache.pop(next(iter(self._history_cache)), None)
            self._history_cache[key] = (monotonic() + max(1, int(ttl)), bars)
            return bars

    async def _fetch_recent_daily_bars(
        self, sym: str, inst_type: str, *, now: datetime | None = None
    ) -> list[HistoricalBar]:
        """Last ~3 daily bars, PostgreSQL-first, one controlled gap-fill allowed."""
        from app.market_data.history_read_service import history_read_service

        to_d = (now or datetime.now(cal.VN_TZ)).date()
        from_d = to_d - timedelta(days=20)
        # CW prices must remain RAW. Underlying series use ADJUSTED consistently with HV.
        adjusted = inst_type != "CW"
        try:
            if settings.DASHBOARD_FALLBACK_GAPFILL:
                bars = await history_read_service.get_history(
                    sym, timeframe="1d", from_date=from_d.isoformat(),
                    to_date=to_d.isoformat(), adjusted=adjusted,
                )
            else:
                bars, _src = await history_read_service.get_history_readonly(
                    sym, timeframe="1d", from_date=from_d.isoformat(),
                    to_date=to_d.isoformat(), adjusted=adjusted,
                )
        except Exception as e:  # noqa: BLE001
            logger.info("resolver: history read for %s failed: %s", sym, e)
            return []
        return list(bars)[-3:]


def _analytics_wire(a) -> dict[str, Any]:
    g = a.greeks
    return {
        "isAvailable": bool(a.is_available),
        "unavailableReason": a.unavailable_reason,
        "ivBid": a.iv_bid,
        "ivTrade": a.iv_trade,
        "ivAsk": a.iv_ask,
        "ivMid": a.iv_mid,
        "historicalVolatility": a.historical_volatility,
        "theoreticalPrice": (g.theoretical_price if g else None),
        "delta": (g.delta if g else None),
        "gamma": (g.gamma if g else None),
        "theta": (g.theta if g else None),
        "vega": (g.vega if g else None),
        "rho": (g.rho if g else None),
        "moneynessRatio": a.moneyness,
        "moneynessCategory": (a.moneyness_category.value if a.moneyness_category else None),
        "contractState": (a.contract_state.value if a.contract_state else None),
        "isTradable": bool(getattr(a, "is_tradable", False)),
        "dte": (a.model_inputs.days_to_expiry if a.model_inputs else None),
        "greeksVolatilitySource": (
            g.volatility_source.value if g and g.volatility_source else "UNAVAILABLE"
        ),
    }


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _iso_ms(ts_ms: Optional[int]) -> Optional[str]:
    if not ts_ms:
        return None
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=cal.VN_TZ).isoformat()


def _parse_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(str(s).strip()[:10])
    except ValueError:
        return None


market_snapshot_resolver = MarketSnapshotResolver()
