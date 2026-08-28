"""
Live Quantitative Analytics Engine for Covered Warrants.
Maintains in-memory quantitative state, fan-out mappings, and event-driven recomputations
for active complete warrants based on realtime market price updates.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Callable, Dict, Optional, Set, Tuple, TYPE_CHECKING

from app.core.config import settings
from app.instruments.instrument_schemas import (
    CoveredWarrantSpecification,
    InstrumentLifecycleStatus,
    DataQualityStatus,
    MetadataVerificationStatus,
)
from app.instruments.instrument_registry import instrument_registry
from app.market_data.market_schemas import CanonicalQuote
from app.quant.quant_schemas import (
    WarrantAnalytics,
    WarrantGreeks,
    QuantModelInputs,
    GreeksVolatilitySource,
    MoneynessCategory,
)
from app.quant.black_scholes import (
    solve_implied_volatility,
    calculate_analytical_greeks,
    bs_call_price_share,
)
from app.quant.dividend_convention import CW_DIVIDEND_YIELD_CONVENTION

if TYPE_CHECKING:
    from app.quant.historical_volatility_service import VolEstimate

logger = logging.getLogger(__name__)

VN_TZ = timezone(timedelta(hours=7))


def get_vietnam_now() -> datetime:
    """Current timestamp in Vietnam timezone (UTC+7)."""
    return datetime.now(VN_TZ)


def calculate_time_to_maturity(maturity_date_str: str, current_time: Optional[datetime] = None) -> Tuple[float, int]:
    """
    Computes time to maturity T in years under ACT/365 convention.
    Target payoff horizon: 15:00:00 (HOSE market close) on maturityDate.
    Returns (T_years, days_to_expiry).
    """
    now = current_time or get_vietnam_now()
    try:
        mat_dt = datetime.strptime(maturity_date_str, "%Y-%m-%d").replace(
            hour=15, minute=0, second=0, tzinfo=VN_TZ
        )
        delta = mat_dt - now
        total_seconds = max(0.0, delta.total_seconds())
        t_years = total_seconds / (365.0 * 86400.0)
        dte = max(0, (mat_dt.date() - now.date()).days)
        return t_years, dte
    except Exception as e:
        logger.warning(f"Failed to parse maturity date '{maturity_date_str}': {e}")
        return 0.0, 0


class LiveQuantEngine:
    def __init__(self):
        self._analytics_cache: Dict[str, WarrantAnalytics] = {}
        self._watched_cw_symbols: Set[str] = set()
        self._underlying_to_cw_map: Dict[str, Set[str]] = {}
        self._market_state_getter = None
        # (underlying_symbol: str) -> Optional[VolEstimate]. MUST be a pure in-memory lookup
        # (no network / disk / blocking I/O): it is invoked on the per-tick calculation path.
        self._historical_vol_getter: Optional[Callable[[str], "Optional[VolEstimate]"]] = None
        self._broadcaster = None
        self._lock = asyncio.Lock()

    def set_market_state_getter(self, getter_func):
        """Injects function to query current market state: (symbol: str) -> Optional[MarketState]"""
        self._market_state_getter = getter_func

    def set_historical_vol_getter(self, getter_func: Callable[[str], "Optional[VolEstimate]"]) -> None:
        """Injects the independent historical-volatility lookup.

        Signature: ``(underlying_symbol: str) -> Optional[VolEstimate]`` where ``VolEstimate``
        carries ``value`` (decimal), ``window`` (sessions) and ``as_of`` (date).

        CONTRACT: this callable is invoked synchronously on the per-tick recompute path and
        MUST be a pure in-memory lookup - no network, disk, or blocking I/O. See
        ``HistoricalVolatilityService.get_estimate``.
        """
        self._historical_vol_getter = getter_func

    def set_broadcaster(self, broadcaster_func):
        """Injects WebSocket broadcast callback: (symbol: str, payload: dict) -> Coroutine"""
        self._broadcaster = broadcaster_func

    def register_watched_cw(self, cw_symbol: str, underlying_symbol: str) -> None:
        """Registers a watched CW into the active quant evaluation pool and fan-out mapping."""
        cw_clean = cw_symbol.strip().upper()
        und_clean = underlying_symbol.strip().upper()

        self._watched_cw_symbols.add(cw_clean)
        if und_clean not in self._underlying_to_cw_map:
            self._underlying_to_cw_map[und_clean] = set()
        self._underlying_to_cw_map[und_clean].add(cw_clean)

    def unregister_watched_cw(self, cw_symbol: str) -> None:
        """Removes a CW from the active evaluation pool."""
        cw_clean = cw_symbol.strip().upper()
        self._watched_cw_symbols.discard(cw_clean)
        for und, cw_set in self._underlying_to_cw_map.items():
            cw_set.discard(cw_clean)

    def get_analytics(self, symbol: str) -> Optional[WarrantAnalytics]:
        """Returns the latest cached quantitative analytics for a symbol."""
        return self._analytics_cache.get(symbol.strip().upper())

    async def compute_warrant_analytics(
        self,
        cw_symbol: str,
        spec: Optional[CoveredWarrantSpecification] = None,
        cw_state: Optional[CanonicalQuote] = None,
        und_state: Optional[CanonicalQuote] = None,
    ) -> WarrantAnalytics:
        """
        Computes full quantitative analytics for a Covered Warrant.
        Enforces strict Data-Quality guards: ACTIVE + COMPLETE + K>0 + CR>0 + T>0.
        """
        now_iso = get_vietnam_now().isoformat()
        cw_sym = cw_symbol.strip().upper()

        # 1. Resolve Instrument Specification
        if not spec:
            spec = await instrument_registry.get_instrument(cw_sym)

        if not spec:
            return WarrantAnalytics(
                symbol=cw_sym,
                underlying_symbol="UNKNOWN",
                calculated_at=now_iso,
                is_available=False,
                unavailable_reason="INSTRUMENT_NOT_IN_REGISTRY",
            )

        und_sym = spec.underlying_symbol.upper()

        # 2. Hard Data-Quality Guard
        if spec.status != InstrumentLifecycleStatus.ACTIVE:
            return WarrantAnalytics(
                symbol=cw_sym,
                underlying_symbol=und_sym,
                calculated_at=now_iso,
                is_available=False,
                unavailable_reason=f"LIFECYCLE_NOT_ACTIVE ({spec.status})",
            )

        if spec.data_quality != DataQualityStatus.COMPLETE:
            return WarrantAnalytics(
                symbol=cw_sym,
                underlying_symbol=und_sym,
                calculated_at=now_iso,
                is_available=False,
                unavailable_reason=f"METADATA_INCOMPLETE ({spec.data_quality})",
            )

        if spec.metadata_verification != MetadataVerificationStatus.VERIFIED_CURRENT:
            return WarrantAnalytics(
                symbol=cw_sym,
                underlying_symbol=und_sym,
                calculated_at=now_iso,
                is_available=False,
                unavailable_reason=f"METADATA_NOT_VERIFIED_CURRENT ({spec.metadata_verification})",
            )

        eff_strike = spec.effective_strike
        if not eff_strike or eff_strike <= 0:
            return WarrantAnalytics(
                symbol=cw_sym,
                underlying_symbol=und_sym,
                calculated_at=now_iso,
                is_available=False,
                unavailable_reason="INVALID_STRIKE_PRICE",
            )

        eff_ratio = spec.effective_ratio
        if not eff_ratio or eff_ratio <= 0:
            return WarrantAnalytics(
                symbol=cw_sym,
                underlying_symbol=und_sym,
                calculated_at=now_iso,
                is_available=False,
                unavailable_reason="INVALID_EXERCISE_RATIO",
            )

        if not spec.maturity_date:
            return WarrantAnalytics(
                symbol=cw_sym,
                underlying_symbol=und_sym,
                calculated_at=now_iso,
                is_available=False,
                unavailable_reason="MISSING_MATURITY_DATE",
            )

        # 3. Time to maturity calculation
        T, dte = calculate_time_to_maturity(spec.maturity_date)
        if T <= 0:
            return WarrantAnalytics(
                symbol=cw_sym,
                underlying_symbol=und_sym,
                calculated_at=now_iso,
                is_available=False,
                unavailable_reason="INSTRUMENT_EXPIRED",
            )

        # 4. Resolve Market States
        if self._market_state_getter:
            if not cw_state:
                cw_state = self._market_state_getter(cw_sym)
            if not und_state:
                und_state = self._market_state_getter(und_sym)

        # Resolve Underlying Spot Price S (prefer last_price -> bid1_price -> ref_price)
        S: Optional[float] = None
        if und_state:
            S = und_state.last_price or und_state.bid1_price or und_state.reference_price

        if not S or S <= 0:
            return WarrantAnalytics(
                symbol=cw_sym,
                underlying_symbol=und_sym,
                calculated_at=now_iso,
                is_available=False,
                unavailable_reason="UNDERLYING_SPOT_PRICE_UNAVAILABLE",
            )

        K = eff_strike
        CR = eff_ratio
        r = settings.QUANT_RISK_FREE_RATE
        # Dividend yield is pinned to the CW convention (q = 0): HOSE covered warrants are
        # dividend-protected via issuer strike/ratio adjustment, so a BSM q > 0 would
        # double-count the protection. See app.quant.dividend_convention. This SAME q is
        # used for the theoretical price, every IV inversion, and every Greek below.
        q = CW_DIVIDEND_YIELD_CONVENTION.value

        # 5. Moneyness (S / K)
        moneyness = round(S / K, 5)
        if moneyness > 1.03:
            moneyness_cat = MoneynessCategory.ITM
        elif moneyness < 0.97:
            moneyness_cat = MoneynessCategory.OTM
        else:
            moneyness_cat = MoneynessCategory.ATM

        # 6. Resolve CW Market Prices
        bid_price: Optional[float] = cw_state.bid1_price if cw_state else None
        ask_price: Optional[float] = cw_state.ask1_price if cw_state else None
        last_price: Optional[float] = cw_state.last_price if cw_state else None

        # 7. Solve Implied Volatilities (Bid, Ask, Trade, Mid)
        iv_bid, _ = solve_implied_volatility(
            S, K, T, r, q, bid_price, exercise_ratio=CR,
            sigma_min=settings.QUANT_IV_SIGMA_MIN,
            sigma_max=settings.QUANT_IV_SIGMA_MAX,
            price_tolerance=settings.QUANT_IV_PRICE_TOLERANCE,
            max_iterations=settings.QUANT_IV_MAX_ITERATIONS,
        ) if (bid_price and bid_price > 0) else (None, None)

        iv_ask, _ = solve_implied_volatility(
            S, K, T, r, q, ask_price, exercise_ratio=CR,
            sigma_min=settings.QUANT_IV_SIGMA_MIN,
            sigma_max=settings.QUANT_IV_SIGMA_MAX,
            price_tolerance=settings.QUANT_IV_PRICE_TOLERANCE,
            max_iterations=settings.QUANT_IV_MAX_ITERATIONS,
        ) if (ask_price and ask_price > 0) else (None, None)

        iv_trade, _ = solve_implied_volatility(
            S, K, T, r, q, last_price, exercise_ratio=CR,
            sigma_min=settings.QUANT_IV_SIGMA_MIN,
            sigma_max=settings.QUANT_IV_SIGMA_MAX,
            price_tolerance=settings.QUANT_IV_PRICE_TOLERANCE,
            max_iterations=settings.QUANT_IV_MAX_ITERATIONS,
        ) if (last_price and last_price > 0) else (None, None)

        # Midpoint IV (if bid and ask exist)
        iv_mid = None
        model_price_mid = None
        if bid_price and ask_price and bid_price > 0 and ask_price > 0:
            mid_p = 0.5 * (bid_price + ask_price)
            iv_mid, _ = solve_implied_volatility(
                S, K, T, r, q, mid_p, exercise_ratio=CR,
                sigma_min=settings.QUANT_IV_SIGMA_MIN,
                sigma_max=settings.QUANT_IV_SIGMA_MAX,
                price_tolerance=settings.QUANT_IV_PRICE_TOLERANCE,
                max_iterations=settings.QUANT_IV_MAX_ITERATIONS,
            )
            if iv_mid is not None and iv_mid > 0:
                model_price_mid = round(bs_call_price_share(S, K, T, r, q, iv_mid) / CR, 2)

        # 8. True Theoretical Fair Price (requires an INDEPENDENT volatility assumption: HV).
        # Invariant: never use IV Mid as theoretical fair value (that would be circular repricing).
        # The provenance label (e.g. "HV_22") comes from the estimate's window - never hardcoded.
        theo_vol: Optional[float] = None
        theo_vol_src = "UNAVAILABLE"
        theo_price: Optional[float] = None

        if self._historical_vol_getter:
            try:
                hv_estimate = self._historical_vol_getter(und_sym)
                if hv_estimate is not None and hv_estimate.value > 0:
                    theo_vol = hv_estimate.value
                    theo_vol_src = hv_estimate.source_label
                    theo_price = round(bs_call_price_share(S, K, T, r, q, theo_vol) / CR, 2)
            except Exception as hve:
                logger.debug(f"Failed to retrieve HV for {und_sym}: {hve}")

        # 9. Greeks Volatility Selection
        # Separate concept: Greeks may use IV_TRADE -> IV_MID -> HISTORICAL_VOL
        vol_for_greeks: Optional[float] = None
        vol_source = GreeksVolatilitySource.UNAVAILABLE

        if iv_trade is not None and iv_trade > 0:
            vol_for_greeks = iv_trade
            vol_source = GreeksVolatilitySource.IV_TRADE
        elif iv_mid is not None and iv_mid > 0:
            vol_for_greeks = iv_mid
            vol_source = GreeksVolatilitySource.IV_MID
        elif theo_vol is not None and theo_vol > 0:
            vol_for_greeks = theo_vol
            vol_source = GreeksVolatilitySource.HISTORICAL_VOL

        # 10. Compute Analytical Greeks
        if vol_for_greeks is not None:
            greeks = calculate_analytical_greeks(
                S, K, T, r, q, vol_for_greeks,
                exercise_ratio=CR,
                volatility_source=vol_source,
                theoretical_price=theo_price,
                model_price_at_iv_mid=model_price_mid,
            )
        else:
            greeks = WarrantGreeks(
                theoretical_price=theo_price,
                model_price_at_iv_mid=model_price_mid,
                volatility_source=GreeksVolatilitySource.UNAVAILABLE,
            )

        # Model Inputs Snapshot
        inputs = QuantModelInputs(
            underlying_price=S,
            strike_price=K,
            exercise_ratio=CR,
            time_to_maturity=round(T, 5),
            days_to_expiry=dte,
            risk_free_rate=r,
            dividend_yield=q,
            market_bid=bid_price,
            market_ask=ask_price,
            market_last=last_price,
        )

        analytics = WarrantAnalytics(
            symbol=cw_sym,
            underlying_symbol=und_sym,
            calculated_at=now_iso,
            is_available=True,
            unavailable_reason=None,
            moneyness=moneyness,
            moneyness_category=moneyness_cat,
            iv_bid=iv_bid,
            iv_trade=iv_trade,
            iv_ask=iv_ask,
            iv_mid=iv_mid,
            historical_volatility=theo_vol,
            theoretical_price=theo_price,
            theoretical_volatility=theo_vol,
            theoretical_volatility_source=theo_vol_src,
            model_price_at_iv_mid=model_price_mid,
            greeks=greeks,
            model_inputs=inputs,
        )

        # Update cache
        self._analytics_cache[cw_sym] = analytics
        return analytics

    async def on_market_state_updated(self, symbol: str, state: CanonicalQuote) -> None:
        """
        Event-driven trigger called when a canonical quote is updated.
        Fans out updates:
        - If symbol is a watched CW: recalculates that CW.
        - If symbol is an underlying equity: recalculates all watched CWs linked to that underlying.
        """
        sym_upper = symbol.strip().upper()

        targets_to_recompute: Set[str] = set()

        # 1. Direct CW update
        if sym_upper in self._watched_cw_symbols:
            targets_to_recompute.add(sym_upper)

        # 2. Underlying equity fan-out update
        if sym_upper in self._underlying_to_cw_map:
            linked_cws = self._underlying_to_cw_map[sym_upper]
            for cw in linked_cws:
                if cw in self._watched_cw_symbols:
                    targets_to_recompute.add(cw)

        if not targets_to_recompute:
            return

        # Recompute all target warrants
        for cw_sym in targets_to_recompute:
            try:
                analytics = await self.compute_warrant_analytics(cw_sym)
                # Broadcast analytics patch to connected WebSocket clients if broadcaster configured
                if self._broadcaster and analytics.is_available:
                    res = self._broadcaster(cw_sym, analytics)
                    if asyncio.iscoroutine(res):
                        await res
            except Exception as e:
                logger.warning(f"Error computing live quant analytics for {cw_sym}: {e}")


# Global singleton instance
live_quant_engine = LiveQuantEngine()
