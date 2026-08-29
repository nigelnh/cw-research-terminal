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
    ContractLifecycleState,
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


def derive_contract_state(
    last_trading_date: Optional[str],
    maturity_date: Optional[str],
    now: Optional[datetime] = None,
) -> Tuple[ContractLifecycleState, bool]:
    """Truthful trading-lifecycle state + whether the warrant is still tradable.

    Uses `last_trading_date` (the date the CW stops trading, ~2 sessions before maturity)
    as the tradability boundary, and `maturity_date` for final expiry. Independent of
    whether analytics could be computed.
    """
    today = (now or get_vietnam_now()).date()
    ltd = mat = None
    try:
        if last_trading_date:
            ltd = datetime.strptime(last_trading_date, "%Y-%m-%d").date()
    except ValueError:
        ltd = None
    try:
        if maturity_date:
            mat = datetime.strptime(maturity_date, "%Y-%m-%d").date()
    except ValueError:
        mat = None

    if mat is None and ltd is None:
        return ContractLifecycleState.UNKNOWN, False
    if mat is not None and today > mat:
        return ContractLifecycleState.EXPIRED, False
    if ltd is not None:
        if today > ltd:
            return ContractLifecycleState.PENDING_MATURITY, False  # matured trading, awaiting settlement
        if today == ltd:
            return ContractLifecycleState.LAST_TRADING_DAY, True
        if (ltd - today).days <= max(0, int(settings.QUANT_NEAR_EXPIRY_DAYS)):
            return ContractLifecycleState.NEAR_EXPIRY, True
        return ContractLifecycleState.ACTIVE, True
    # only maturity known
    return ContractLifecycleState.ACTIVE, True


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
    """Live Covered-Warrant analytics with latest-wins, single-flight-per-symbol scheduling.

    Concurrency contract
    --------------------
    * Every market tick calls ``notify_market_tick(symbol)`` (synchronous, event-loop thread).
      It resolves affected CW symbols and, for each, records a strictly increasing
      *generation* in ``_pending`` and ensures exactly one worker task is running for that
      symbol (``_inflight``). A burst of ticks for one symbol is coalesced to a single
      pending generation - intermediate states are skipped, the newest is always computed.
    * A per-symbol worker (``_symbol_worker``) drains ``_pending[symbol]``: it takes a
      COHERENT input snapshot (spec + underlying quote + CW quote, read back-to-back with
      no ``await`` between them), computes analytics via the unchanged
      ``compute_warrant_analytics``, and publishes ONLY if its generation is >= the
      generation already in the cache. A stale computation therefore cannot overwrite a
      newer one (double-guarded: single-flight + generation check).
    * Different symbols run independently, bounded globally by ``_compute_sem``
      (``QUANT_MAX_CONCURRENT_COMPUTES``). No global lock serialises unrelated symbols.
    * ``_analytics_cache`` is written ONLY by ``_publish`` (generation-guarded).
      ``compute_warrant_analytics`` is a pure function with no cache side effect.
    * All engine tasks are retained in ``_tasks`` with done-callbacks that consume
      exceptions; ``shutdown()`` cancels them and blocks new scheduling.
    """

    def __init__(self):
        self._analytics_cache: Dict[str, WarrantAnalytics] = {}
        self._watched_cw_symbols: Set[str] = set()
        self._underlying_to_cw_map: Dict[str, Set[str]] = {}
        self._market_state_getter = None
        # (underlying_symbol: str) -> Optional[VolEstimate]. MUST be a pure in-memory lookup
        # (no network / disk / blocking I/O): it is invoked on the per-tick calculation path.
        self._historical_vol_getter: Optional[Callable[[str], "Optional[VolEstimate]"]] = None
        self._broadcaster = None

        # ---- latest-wins scheduling state (all mutated only on the event-loop thread) ----
        self._generation: int = 0                          # monotonic; ++ on every schedule
        self._pending: Dict[str, int] = {}                 # cw_sym -> newest requested generation
        self._inflight: Dict[str, asyncio.Task] = {}       # cw_sym -> its running worker task
        self._cache_generation: Dict[str, int] = {}        # cw_sym -> generation of cached analytics
        self._tasks: Set[asyncio.Task] = set()             # strong refs to every engine task
        self._compute_sem = asyncio.Semaphore(
            max(1, int(settings.QUANT_MAX_CONCURRENT_COMPUTES))
        )
        self._shutting_down: bool = False
        self._counters: Dict[str, int] = {
            "scheduled": 0,          # schedule requests recorded as pending
            "coalesced": 0,          # ticks absorbed into an existing pending/inflight
            "computed": 0,           # compute_warrant_analytics invocations from the scheduler
            "published": 0,          # generation-guarded cache writes + broadcasts
            "stale_discarded": 0,    # computed results dropped because a newer generation won
            "failures": 0,           # compute exceptions (cache preserved, worker survives)
            "broadcast_errors": 0,
        }

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
        """Injects the analytics broadcast callback: ``(symbol: str, analytics: WarrantAnalytics)``.

        CONTRACT: synchronous and non-blocking (it should hand off to the WS layer and
        return immediately). It is invoked from the generation-guarded ``_publish``, so it
        is only ever called with the latest accepted analytics, in generation order. A
        coroutine return value is scheduled as a tracked task defensively, but the
        supported contract is a plain function.
        """
        self._broadcaster = broadcaster_func

    def register_watched_cw(self, cw_symbol: str, underlying_symbol: str) -> None:
        """Registers a watched CW into the active quant evaluation pool and fan-out mapping.

        Also schedules an initial recompute so a freshly-subscribed CW gets analytics
        promptly rather than only on its next tick.
        """
        cw_clean = cw_symbol.strip().upper()
        und_clean = underlying_symbol.strip().upper()

        self._watched_cw_symbols.add(cw_clean)
        if und_clean not in self._underlying_to_cw_map:
            self._underlying_to_cw_map[und_clean] = set()
        self._underlying_to_cw_map[und_clean].add(cw_clean)

        self._schedule_recompute(cw_clean)

    def unregister_watched_cw(self, cw_symbol: str) -> None:
        """Removes a CW from the active evaluation pool and tears down its scheduling state."""
        cw_clean = cw_symbol.strip().upper()
        self._watched_cw_symbols.discard(cw_clean)
        for _und, cw_set in self._underlying_to_cw_map.items():
            cw_set.discard(cw_clean)

        self._pending.pop(cw_clean, None)
        self._cache_generation.pop(cw_clean, None)
        self._analytics_cache.pop(cw_clean, None)
        task = self._inflight.pop(cw_clean, None)
        if task is not None and not task.done():
            task.cancel()

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
        """Full CW analytics, then stamp the truthful contract-lifecycle state onto the
        result (even when analytics are unavailable). If the warrant is no longer tradable
        (past its last trading date) the greeks/IV are cleared and `is_available` is forced
        False - intrinsic value may still be mathematically defined, but the UI must not
        present live tradable analytics for a non-tradable contract."""
        analytics = await self._compute_warrant_analytics_inner(cw_symbol, spec, cw_state, und_state)
        resolved = spec or await instrument_registry.get_instrument(cw_symbol.strip().upper())
        if resolved is not None:
            cstate, tradable = derive_contract_state(resolved.last_trading_date, resolved.maturity_date)
        else:
            cstate, tradable = ContractLifecycleState.UNKNOWN, False
        analytics.contract_state = cstate
        analytics.is_tradable = tradable
        if not tradable and analytics.is_available:
            analytics.is_available = False
            analytics.unavailable_reason = f"NOT_TRADABLE ({cstate.value})"
            analytics.iv_bid = analytics.iv_trade = analytics.iv_ask = analytics.iv_mid = None
            analytics.greeks = WarrantGreeks()
        return analytics

    async def _compute_warrant_analytics_inner(
        self,
        cw_symbol: str,
        spec: Optional[CoveredWarrantSpecification] = None,
        cw_state: Optional[CanonicalQuote] = None,
        und_state: Optional[CanonicalQuote] = None,
    ) -> WarrantAnalytics:
        """
        Computes full quantitative analytics for a Covered Warrant.
        Enforces strict Data-Quality guards: ACTIVE + COMPLETE + K>0 + CR>0 + T>0.

        PURE: returns the analytics, does NOT write ``_analytics_cache``. The live cache is
        owned exclusively by the generation-guarded ``_publish`` on the scheduler path.
        Callers that want the live cached value use ``get_analytics``. When ``spec``,
        ``cw_state`` and ``und_state`` are all supplied this coroutine has no suspension
        point - it reads one coherent input and runs to completion atomically.
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

        # 5. Moneyness (S / K). `moneyness` is the raw numeric ratio; `moneyness_cat` is the
        #    categorical UI label, ATM iff |S/K - 1| <= QUANT_MONEYNESS_ATM_BAND (default 3%).
        #    For a call CW: S > K is in-the-money. The band is a display convention only and
        #    never feeds the BSM computation below.
        moneyness = round(S / K, 5)
        atm_band = max(0.0, float(settings.QUANT_MONEYNESS_ATM_BAND))
        if moneyness > 1.0 + atm_band:
            moneyness_cat = MoneynessCategory.ITM
        elif moneyness < 1.0 - atm_band:
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
        return analytics

    # ------------------------------------------------------------------ #
    # Latest-wins scheduling (all sync methods run on the loop thread)
    # ------------------------------------------------------------------ #
    def startup(self) -> None:
        """Re-arm the scheduler (clears a prior ``shutdown``). Called from app startup."""
        self._shutting_down = False

    def notify_market_tick(self, symbol: str) -> None:
        """Synchronous entry from the market-data tick path.

        Resolves the CW symbols affected by a tick on ``symbol`` (the symbol itself if it
        is a watched CW, plus every watched CW whose underlying is ``symbol``) and
        schedules a latest-wins recompute for each. Never blocks, never awaits, never
        raises. Creates at most one worker task per affected CW.
        """
        if self._shutting_down:
            return
        sym_upper = symbol.strip().upper()

        targets: Set[str] = set()
        if sym_upper in self._watched_cw_symbols:
            targets.add(sym_upper)
        linked = self._underlying_to_cw_map.get(sym_upper)
        if linked:
            targets.update(cw for cw in linked if cw in self._watched_cw_symbols)

        for cw_sym in targets:
            self._schedule_recompute(cw_sym)

    def _schedule_recompute(self, cw_sym: str) -> None:
        """Record the newest generation for ``cw_sym`` and ensure a worker is running."""
        if self._shutting_down:
            return
        if self._market_state_getter is None:
            # Not wired yet (e.g. unit test constructed the engine directly); nothing to do.
            return

        self._generation += 1
        self._pending[cw_sym] = self._generation      # latest-wins: overwrite any older want
        self._counters["scheduled"] += 1

        existing = self._inflight.get(cw_sym)
        if existing is not None and not existing.done():
            # A worker is already draining this symbol; it will pick up the new generation.
            self._counters["coalesced"] += 1
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop (sync context). The pending generation stays recorded; the
            # next _schedule_recompute made under a loop will start the worker.
            return

        task = loop.create_task(self._symbol_worker(cw_sym))
        self._inflight[cw_sym] = task
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            # Should not happen (_symbol_worker guards internally) - retrieve so asyncio
            # does not log "Task exception was never retrieved".
            logger.error("LiveQuantEngine worker task crashed: %r", exc)

    async def _symbol_worker(self, cw_sym: str) -> None:
        """Drains ``_pending[cw_sym]`` one generation at a time. Single-flight per symbol."""
        try:
            while not self._shutting_down:
                want = self._pending.pop(cw_sym, None)
                if want is None:
                    break

                async with self._compute_sem:
                    if self._shutting_down:
                        break
                    # Coalesce anything that arrived while we queued for the semaphore.
                    newer = self._pending.pop(cw_sym, None)
                    if newer is not None:
                        self._counters["coalesced"] += 1
                        want = newer
                    try:
                        analytics = await self._compute_for_symbol(cw_sym, want)
                        self._counters["computed"] += 1
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - one bad tick must not kill the worker
                        self._counters["failures"] += 1
                        logger.warning(
                            "Live quant recompute failed for %s (generation %d): %s: %s "
                            "- cached analytics preserved",
                            cw_sym, want, exc.__class__.__name__, exc,
                        )
                        # Advance nothing; loop to see if a newer tick is pending.
                        await asyncio.sleep(0)
                        continue

                self._publish(cw_sym, want, analytics)
                await asyncio.sleep(0)  # fairness: let other symbols' workers run
        except asyncio.CancelledError:
            raise
        finally:
            self._inflight.pop(cw_sym, None)
            # A tick may have landed after our last pending-check; re-arm if so.
            if not self._shutting_down and self._pending.get(cw_sym) is not None:
                self._schedule_recompute(cw_sym)

    async def _compute_for_symbol(self, cw_sym: str, generation: int) -> WarrantAnalytics:
        """Resolve a COHERENT input snapshot, then compute. This is the scheduler's only
        awaiting seam and the natural override point for concurrency tests.

        ``generation`` is the monotonic ordering token for this recompute (used by the
        caller for the latest-wins publish decision; passed here so tests can correlate).

        The spec is resolved first (a registry lookup that only suspends on the very first
        call before init). The two market-state reads are then issued back-to-back with no
        ``await`` between them, so S (underlying) and the CW book come from the same instant.
        ``compute_warrant_analytics`` with spec + both states supplied has no suspension
        point, so the whole computation uses that one snapshot.
        """
        spec = await instrument_registry.get_instrument(cw_sym)
        und_sym = spec.underlying_symbol.strip().upper() if (spec and spec.underlying_symbol) else None

        getter = self._market_state_getter
        cw_state = getter(cw_sym) if getter else None
        und_state = getter(und_sym) if (getter and und_sym) else None

        return await self.compute_warrant_analytics(
            cw_sym, spec=spec, cw_state=cw_state, und_state=und_state
        )

    def _publish(self, cw_sym: str, generation: int, analytics: WarrantAnalytics) -> None:
        """Generation-guarded cache write + broadcast. Older generations are discarded."""
        if generation < self._cache_generation.get(cw_sym, -1):
            self._counters["stale_discarded"] += 1
            return

        self._analytics_cache[cw_sym] = analytics
        self._cache_generation[cw_sym] = generation
        self._counters["published"] += 1

        if self._broadcaster is not None and analytics.is_available and not self._shutting_down:
            try:
                res = self._broadcaster(cw_sym, analytics)
                if asyncio.iscoroutine(res):
                    try:
                        t = asyncio.get_running_loop().create_task(res)
                        self._tasks.add(t)
                        t.add_done_callback(self._on_task_done)
                    except RuntimeError:
                        res.close()
            except Exception as exc:  # noqa: BLE001
                self._counters["broadcast_errors"] += 1
                logger.warning("Analytics broadcast failed for %s: %s", cw_sym, exc)

    async def shutdown(self) -> None:
        """Block new scheduling and cancel/await every engine task. Idempotent."""
        self._shutting_down = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._inflight.clear()
        self._pending.clear()
        logger.info("LiveQuantEngine scheduler shut down (%s).", self.stats())

    def stats(self) -> Dict[str, int]:
        """Lightweight observability snapshot for logs and tests."""
        return {
            **self._counters,
            "inflight_workers": len(self._inflight),
            "pending_symbols": len(self._pending),
            "tracked_tasks": len(self._tasks),
            "cached_symbols": len(self._analytics_cache),
            "generation": self._generation,
        }


# Global singleton instance
live_quant_engine = LiveQuantEngine()
