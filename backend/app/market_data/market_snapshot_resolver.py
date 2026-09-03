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

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

from app.core.config import settings
from app.market_data import trading_calendar as cal
from app.market_data.market_schemas import HistoricalBar
from app.market_data.market_session import market_session
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
    "total_volume", "trading_value", "underlying_price",
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
            if b > 0:
                spread_pct = round((a - b) / b * 100.0, 4)

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

    def configure(self, sessionmaker) -> None:
        self._sm = sessionmaker

    async def resolve_rows(
        self, symbols: list[str], *, now: Optional[datetime] = None, diag: bool = False
    ) -> list[ResolvedRow]:
        now = now or datetime.now(cal.VN_TZ)
        clean = list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))
        latest_session = cal.latest_completed_trading_session(now)
        session_active = cal.is_trading_active(now)

        # Batch-load snapshots + registry underlyings once.
        snapshots = await self._load_snapshots(clean)
        rows: list[ResolvedRow] = []
        for sym in clean:
            rows.append(
                await self._resolve_one(
                    sym, now=now, latest_session=latest_session,
                    session_active=session_active, snapshot=snapshots.get(sym), diag=diag,
                )
            )
        return rows

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
        snapshot, diag: bool,
    ) -> ResolvedRow:
        inst_type = market_state._determine_instrument_type(sym)
        row = ResolvedRow(symbol=sym, instrument_type=inst_type)
        trace: list[str] = []

        if inst_type == "CW":
            await self._attach_analytics(row, sym, now=now, latest_session=latest_session,
                                        session_active=session_active)

        # ---- A. LIVE ------------------------------------------------- #
        live = market_state.get_quote(sym)
        live_ok = (
            session_active
            and live is not None
            and market_session.is_display_eligible(live.received_timestamp, now)
        )
        if live_ok and live is not None:
            row.instrument_type = live.instrument_type or inst_type
            for f in _QUOTE_FIELDS:
                row.values[f] = getattr(live, f, None)
            for f in _BOOK_FIELDS:
                row.values[f] = getattr(live, f, None)
            row.underlying_symbol = live.underlying_symbol
            as_of = _iso_ms(live.received_timestamp)
            sd = now.date().isoformat()
            row.quote_prov = FieldProvenance(DataTemporalState.LIVE, DataSource.LIVE_FEED, as_of, sd)
            row.book_prov = FieldProvenance(DataTemporalState.LIVE, DataSource.LIVE_FEED, as_of, sd)
            row.is_realtime_eligible = True
            trace.append("A:LIVE")
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
            if row.values.get("reference_price") is None:
                await self._fill_live_reference(
                    row, sym, inst_type=inst_type, snapshot=snapshot,
                    latest_session=latest_session, now=now, trace=trace,
                )
            if diag:
                row.diag = {"chosen": "LIVE", "trace": trace}
            return row

        # ---- B. LAST_SESSION snapshot ------------------------------- #
        if snapshot is not None:
            snap_session = snapshot.session_date
            snap_stale = snap_session < latest_session
            as_of = snapshot.captured_at.isoformat() if snapshot.captured_at else None
            sd = snap_session.isoformat()
            for f in _QUOTE_FIELDS:
                row.values[f] = _num(getattr(snapshot, f, None))
            row.underlying_symbol = snapshot.underlying_symbol
            src = (
                DataSource.SNAPSHOT_FINAL if snapshot.quality == "FINAL"
                else DataSource.SNAPSHOT_SEED if snapshot.quality == "SEED"
                else DataSource.SNAPSHOT_CHECKPOINT
            )
            row.quote_prov = FieldProvenance(
                DataTemporalState.LAST_SESSION if not snap_stale else DataTemporalState.HISTORICAL,
                src, as_of, sd, stale=snap_stale,
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
                    DataTemporalState.LAST_SESSION if not snap_stale else DataTemporalState.HISTORICAL,
                    src, as_of, sd, stale=snap_stale,
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
            if not snap_stale and all(row.values.get(f) is not None for f in history_fields):
                if diag:
                    row.diag = {"chosen": "SNAPSHOT", "trace": trace}
                return row

        # ---- C. HISTORICAL / EOD bars ------------------------------ #
        bars = await self._recent_daily_bars(sym, inst_type, now=now)
        if bars:
            last_bar = bars[-1]
            prev_close = bars[-2].close if len(bars) >= 2 else None
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
            if resolved_close is not None and resolved_reference not in (None, 0):
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
        """Last ~3 daily bars, PostgreSQL-first, one controlled gap-fill allowed."""
        from app.market_data.history_read_service import history_read_service

        to_d = (now or datetime.now(cal.VN_TZ)).date()
        from_d = to_d - timedelta(days=20)
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
