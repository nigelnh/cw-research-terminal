"""
Tests for HistoricalVolatilityService and its wiring into LiveQuantEngine (P0-1).

Covers:
* pure in-memory getter (no I/O on the per-tick path)
* successful warm-up
* provider failure -> service stays operational
* insufficient history -> None, no crash
* multiple CWs sharing one underlying -> a single upstream fetch
* concurrent refreshes single-flighted
* adjusted=True requested; timeframe 1D
* stale estimates treated as unavailable
* upstream source is swappable (PostgreSQL-ready) without touching LiveQuantEngine
* theoretical_price / theoretical_volatility / historical_volatility / source populated when valid HV exists
* HISTORICAL_VOL Greeks fallback when market IV is unavailable
* application startup survives HV warm-up failure (does not crash)

No test performs a real FiinQuant request.
"""

import asyncio
from datetime import date, datetime, timedelta

import pytest
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.quant.black_scholes import bs_call_price_share
from app.quant.dividend_convention import CW_DIVIDEND_YIELD_CONVENTION
from app.quant.historical_volatility import calculate_historical_volatility
from app.quant.historical_volatility_service import (
    HistoricalVolatilityService,
    VolEstimate,
    historical_volatility_service,
)
from app.quant.quant_engine import (
    VN_TZ,
    LiveQuantEngine,
    calculate_time_to_maturity,
    live_quant_engine,
)
import app.quant.quant_engine as quant_engine_module
from app.quant.quant_schemas import GreeksVolatilitySource
from app.instruments.instrument_schemas import (
    CoveredWarrantSpecification,
    InstrumentLifecycleStatus,
    DataQualityStatus,
    LifecycleEvidenceLevel,
    MetadataVerificationStatus,
)
from app.market_data.market_schemas import CanonicalQuote
from tests.fixtures.fake_bar_source import FakeBarSource, make_daily_bars, synthetic_closes

CLOSES = synthetic_closes(40, base=22000.0)
_EXPECTED_HV = calculate_historical_volatility(
    CLOSES, window=settings.QUANT_HV_WINDOW_SESSIONS, min_periods=settings.QUANT_HV_MIN_SESSIONS
)
assert _EXPECTED_HV is not None and _EXPECTED_HV > 0, "synthetic fixture must yield a valid HV"
EXPECTED_HV: float = _EXPECTED_HV


def _hpg_source() -> FakeBarSource:
    return FakeBarSource({"HPG": make_daily_bars(CLOSES)})


def _active_cw_spec(symbol: str = "CHPG2602", underlying: str = "HPG") -> CoveredWarrantSpecification:
    return CoveredWarrantSpecification(
        symbol=symbol,
        issuer="TCBS",
        underlying_symbol=underlying,
        strike_price=25885.0,
        exercise_ratio=3.5704,
        maturity_date="2026-09-21",
        last_trading_date="2026-09-17",
        listed_volume=10_000_000,
        issue_price=1000.0,
        status=InstrumentLifecycleStatus.ACTIVE,
        data_quality=DataQualityStatus.COMPLETE,
        evidence_level=LifecycleEvidenceLevel.CURRENT_EXCHANGE_LIST,
        metadata_verification=MetadataVerificationStatus.VERIFIED_CURRENT,
    )


@pytest.fixture(autouse=True)
def _restore_singleton():
    """Snapshot and restore the module singleton so tests don't leak state."""
    svc = historical_volatility_service
    saved = (dict(svc._cache), dict(svc._locks), set(svc._pending), svc._source)
    svc._cache.clear()
    svc._locks.clear()
    svc._pending.clear()
    svc._source = None
    yield
    svc._cache.clear(); svc._cache.update(saved[0])
    svc._locks.clear(); svc._locks.update(saved[1])
    svc._pending.clear(); svc._pending.update(saved[2])
    svc._source = saved[3]


# --------------------------------------------------------------------------- #
# Service unit behavior
# --------------------------------------------------------------------------- #

def test_expected_hv_fixture_is_meaningful():
    assert EXPECTED_HV is not None and EXPECTED_HV > 0


def test_getter_is_pure_before_any_refresh():
    svc = HistoricalVolatilityService(bar_source=_hpg_source())
    # No awaits, no I/O, just a dict miss.
    assert svc.get_estimate("HPG") is None
    assert svc.get_value("HPG") is None
    assert svc.has_fresh("HPG") is False


@pytest.mark.asyncio
async def test_successful_warm_populates_cache_with_provenance():
    src = _hpg_source()
    svc = HistoricalVolatilityService(bar_source=src)

    result = await svc.warm(["HPG"])

    est = svc.get_estimate("HPG")
    assert isinstance(est, VolEstimate)
    assert est.value == EXPECTED_HV
    assert est.window == settings.QUANT_HV_WINDOW_SESSIONS == 22
    assert est.source_label == "HV_22"
    assert est.as_of == date.today() or (date.today() - est.as_of).days <= 1  # VN date may differ by <1d
    assert svc.get_value("HPG") == EXPECTED_HV
    assert result["HPG"] is est
    # adjusted=True + daily bars requested
    assert src.calls[0]["adjusted"] is True
    assert src.calls[0]["timeframe"] == "1D"
    assert src.call_count_by_symbol["HPG"] == 1


@pytest.mark.asyncio
async def test_provider_failure_leaves_service_operational():
    failing = FakeBarSource(fail=True, fail_exc=RuntimeError("upstream 503"))
    svc = HistoricalVolatilityService(bar_source=failing)

    est = await svc.refresh("HPG")  # must not raise

    assert est is None
    assert svc.get_estimate("HPG") is None
    assert failing.call_count_by_symbol["HPG"] == 1

    # Recovery: swap in a working source and refresh again.
    svc.set_bar_source(_hpg_source())
    est2 = await svc.refresh("HPG")
    assert est2 is not None and est2.value == EXPECTED_HV


@pytest.mark.asyncio
async def test_insufficient_history_returns_none_without_crash():
    short = FakeBarSource({"HPG": make_daily_bars(synthetic_closes(6))})
    svc = HistoricalVolatilityService(bar_source=short)

    est = await svc.refresh("HPG")

    assert est is None
    assert svc.get_estimate("HPG") is None
    assert short.call_count_by_symbol["HPG"] == 1


@pytest.mark.asyncio
async def test_multiple_cws_one_underlying_cause_single_fetch():
    src = _hpg_source()
    svc = HistoricalVolatilityService(bar_source=src)

    await svc.warm(["HPG"])

    # Simulate 3 CWs (CHPG2602, CHPG2541, CHPG2705) all pricing off HPG on the per-tick path.
    for _ in range(3):
        assert svc.get_value("HPG") == EXPECTED_HV  # pure lookup, no fetch

    assert src.call_count_by_symbol["HPG"] == 1


@pytest.mark.asyncio
async def test_concurrent_refreshes_are_single_flighted():
    src = _hpg_source()
    src._call_delay = 0.05  # force overlap
    svc = HistoricalVolatilityService(bar_source=src)

    results = await asyncio.gather(
        svc.refresh("HPG"), svc.refresh("HPG"), svc.refresh("HPG"), svc.refresh("hpg")
    )

    assert src.call_count_by_symbol["HPG"] == 1
    assert all(r is not None and r.value == EXPECTED_HV for r in results)


@pytest.mark.asyncio
async def test_warm_dedups_case_and_whitespace():
    src = _hpg_source()
    svc = HistoricalVolatilityService(bar_source=src)

    await svc.warm(["HPG", "hpg", "  HPG  ", "hPg"])

    assert src.call_count_by_symbol["HPG"] == 1


@pytest.mark.asyncio
async def test_ensure_is_bounded_and_nonblocking():
    src = _hpg_source()
    src._call_delay = 0.02
    svc = HistoricalVolatilityService(bar_source=src)

    # Fire many ensure() calls in a sync burst (as the WS subscribe handler would).
    for _ in range(6):
        svc.ensure("HPG")
    assert svc.get_estimate("HPG") is None  # not blocking - not resolved yet

    # Let the single bounded task finish.
    for _ in range(50):
        if svc.get_estimate("HPG") is not None:
            break
        await asyncio.sleep(0.01)

    assert svc.get_value("HPG") == EXPECTED_HV
    assert src.call_count_by_symbol["HPG"] == 1
    assert svc.stats()["pending_ensures"] == []


@pytest.mark.asyncio
async def test_ensure_no_op_when_already_fresh():
    src = _hpg_source()
    svc = HistoricalVolatilityService(bar_source=src)
    await svc.warm(["HPG"])

    svc.ensure("HPG")
    await asyncio.sleep(0.02)

    assert src.call_count_by_symbol["HPG"] == 1  # no extra fetch


def test_stale_estimate_treated_as_unavailable():
    svc = HistoricalVolatilityService(bar_source=_hpg_source())
    stale_day = date.today() - timedelta(days=settings.QUANT_HV_MAX_STALE_DAYS + 10)
    svc._cache["HPG"] = VolEstimate(value=0.30, window=22, as_of=stale_day)

    assert svc.get_estimate("HPG") is None
    assert svc.get_value("HPG") is None


@pytest.mark.asyncio
async def test_upstream_source_is_swappable_without_engine_changes():
    """Demonstrates the PostgreSQL swap-point: only set_bar_source() changes."""
    src_a = FakeBarSource({"HPG": make_daily_bars(synthetic_closes(40, base=20000.0))})
    src_b = FakeBarSource({"HPG": make_daily_bars(synthetic_closes(40, base=50000.0))})
    svc = HistoricalVolatilityService(bar_source=src_a)

    await svc.refresh("HPG")
    hv_a = svc.get_value("HPG")

    svc.set_bar_source(src_b)
    await svc.refresh("HPG", force=True)
    hv_b = svc.get_value("HPG")

    assert hv_a is not None and hv_b is not None
    assert src_a.call_count_by_symbol["HPG"] == 1
    assert src_b.call_count_by_symbol["HPG"] == 1


@pytest.mark.asyncio
async def test_refresh_noop_when_no_source():
    svc = HistoricalVolatilityService(bar_source=None)
    assert await svc.refresh("HPG") is None  # no crash, no I/O
    assert svc.stats()["source_wired"] is False


# --------------------------------------------------------------------------- #
# LiveQuantEngine integration (real service, real wiring)
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_engine_theoretical_price_populated_with_real_service():
    svc = HistoricalVolatilityService(bar_source=_hpg_source())
    await svc.warm(["HPG"])

    engine = LiveQuantEngine()
    engine.set_historical_vol_getter(svc.get_estimate)  # production wiring

    spec = _active_cw_spec()
    und_quote = CanonicalQuote(symbol="HPG", instrument_type="STOCK", last_price=22150.0)
    cw_quote = CanonicalQuote(
        symbol="CHPG2602", instrument_type="CW", bid1_price=40.0, ask1_price=50.0, last_price=None
    )

    analytics = await engine.compute_warrant_analytics(
        "CHPG2602", spec=spec, cw_state=cw_quote, und_state=und_quote
    )

    assert analytics.is_available is True
    assert analytics.theoretical_price is not None
    assert analytics.theoretical_volatility == EXPECTED_HV
    assert analytics.theoretical_volatility_source == "HV_22"
    assert analytics.historical_volatility == EXPECTED_HV
    assert analytics.greeks.theoretical_price is not None

    assert analytics.model_inputs is not None
    T = analytics.model_inputs.time_to_maturity
    assert T is not None
    expected = round(
        bs_call_price_share(
            22150.0, 25885.0, T, settings.QUANT_RISK_FREE_RATE,
            CW_DIVIDEND_YIELD_CONVENTION.value, EXPECTED_HV
        )
        / 3.5704,
        2,
    )
    assert abs(analytics.theoretical_price - expected) < 0.05
    # Invariant preserved: independent theo price != circular IV-mid repricing
    assert analytics.model_price_at_iv_mid is not None
    assert analytics.theoretical_price != analytics.model_price_at_iv_mid


@pytest.mark.asyncio
async def test_engine_historical_vol_greeks_fallback_when_no_market_iv():
    svc = HistoricalVolatilityService(bar_source=_hpg_source())
    await svc.warm(["HPG"])

    engine = LiveQuantEngine()
    engine.set_historical_vol_getter(svc.get_estimate)

    spec = _active_cw_spec()
    und_quote = CanonicalQuote(symbol="HPG", instrument_type="STOCK", last_price=22150.0)
    # No trade, no bid, no ask -> no market IV of any kind.
    cw_quote = CanonicalQuote(
        symbol="CHPG2602", instrument_type="CW", bid1_price=None, ask1_price=None, last_price=None
    )

    analytics = await engine.compute_warrant_analytics(
        "CHPG2602", spec=spec, cw_state=cw_quote, und_state=und_quote
    )

    assert analytics.is_available is True
    assert analytics.iv_bid is None and analytics.iv_ask is None and analytics.iv_trade is None
    assert analytics.greeks.volatility_source == GreeksVolatilitySource.HISTORICAL_VOL
    assert analytics.greeks.volatility_used == round(EXPECTED_HV, 4)
    assert analytics.greeks.delta is not None
    assert analytics.greeks.gamma is not None
    assert analytics.greeks.theta is not None
    assert analytics.greeks.vega is not None
    assert analytics.greeks.rho is not None


@pytest.mark.asyncio
async def test_engine_theoretical_price_none_without_service():
    """Regression: bare engine (no getter wired) still yields None, never a circular value."""
    engine = LiveQuantEngine()  # no set_historical_vol_getter

    spec = _active_cw_spec()
    und_quote = CanonicalQuote(symbol="HPG", instrument_type="STOCK", last_price=22150.0)
    cw_quote = CanonicalQuote(
        symbol="CHPG2602", instrument_type="CW", bid1_price=40.0, ask1_price=50.0, last_price=None
    )

    analytics = await engine.compute_warrant_analytics(
        "CHPG2602", spec=spec, cw_state=cw_quote, und_state=und_quote
    )

    assert analytics.is_available is True
    assert analytics.theoretical_price is None
    assert analytics.theoretical_volatility is None
    assert analytics.theoretical_volatility_source == "UNAVAILABLE"


@pytest.fixture
def frozen_vn_now(monkeypatch):
    """Freeze the engine's Vietnam wall-clock. ``calculate_time_to_maturity`` resolves
    ``get_vietnam_now`` from the engine module at call time, so this pins T for both the
    engine and any reconstruction the test performs. Returns a setter for the instant."""

    holder = {"now": datetime(2026, 8, 29, 10, 0, 0, tzinfo=VN_TZ)}
    monkeypatch.setattr(quant_engine_module, "get_vietnam_now", lambda: holder["now"])

    def _set(dt: datetime) -> None:
        holder["now"] = dt

    return _set


async def _assert_engine_provenance_consistent(a, spec) -> None:
    """Every reported figure is reproducible from the SAME canonical inputs the engine
    used - not from the display-rounded ``model_inputs`` echoes. The clock is frozen by
    the ``frozen_vn_now`` fixture, so ``T`` here is byte-identical to the engine's."""
    from app.quant.black_scholes import bs_call_price_share, calculate_analytical_greeks

    mi = a.model_inputs
    assert mi is not None
    assert a.theoretical_volatility is not None and a.moneyness is not None

    # canonical inputs (full precision), recomputed exactly as production does
    S = mi.underlying_price
    K = mi.strike_price
    r = mi.risk_free_rate
    q = mi.dividend_yield
    CR = mi.exercise_ratio
    T_full, dte = calculate_time_to_maturity(spec.maturity_date)

    # 1. model_inputs echo the settings + effective contract terms
    assert r == settings.QUANT_RISK_FREE_RATE
    assert q == CW_DIVIDEND_YIELD_CONVENTION.value == 0.0
    assert K == spec.effective_strike == 25885.0
    assert CR == spec.effective_ratio == 3.5704
    assert S == 22150.0

    # 1b. the ROUNDED echoes have the intended relationship to the internal values
    #     (they are display values, deliberately not the numbers used in the math).
    assert mi.time_to_maturity == round(T_full, 5)
    assert mi.days_to_expiry == dte
    assert a.iv_trade is not None
    assert a.greeks.volatility_used == round(a.iv_trade, 4)  # 4dp display; greeks use a.iv_trade

    # 2. moneyness is exactly S / K
    assert a.moneyness == round(S / K, 5)

    # 3. theoretical_price == round( BS(canonical inputs, HV) / ratio , 2 )
    assert a.theoretical_volatility_source == "HV_22"
    assert a.theoretical_volatility == EXPECTED_HV == a.historical_volatility
    reprice = round(
        bs_call_price_share(S, K, T_full, r, q, a.theoretical_volatility) / CR, 2
    )
    assert a.theoretical_price == reprice

    # 4. Greeks reproduce EXACTLY from (canonical T, the iv_trade the analytics reports).
    #    Both paths apply identical output rounding, so this is strict equality - no tolerance.
    assert a.greeks.volatility_source == GreeksVolatilitySource.IV_TRADE
    direct = calculate_analytical_greeks(S, K, T_full, r, q, a.iv_trade, exercise_ratio=CR)
    assert a.greeks.delta == direct.delta
    assert a.greeks.gamma == direct.gamma
    assert a.greeks.vega == direct.vega
    assert a.greeks.theta == direct.theta
    assert a.greeks.rho == direct.rho

    # 5. the independent theo price is NOT the circular IV-mid repricing
    assert a.model_price_at_iv_mid is not None
    assert a.theoretical_price != a.model_price_at_iv_mid


async def _compute_reference_analytics(engine):
    spec = _active_cw_spec()
    und = CanonicalQuote(symbol="HPG", instrument_type="STOCK", last_price=22150.0)
    cw = CanonicalQuote(
        symbol="CHPG2602", instrument_type="CW",
        bid1_price=42.0, ask1_price=48.0, last_price=45.0,
    )
    a = await engine.compute_warrant_analytics("CHPG2602", spec=spec, cw_state=cw, und_state=und)
    return a, spec


@pytest.mark.asyncio
async def test_engine_analytics_provenance_is_internally_consistent(frozen_vn_now):
    """End-to-end: market/instrument inputs -> LiveQuantEngine -> WarrantAnalytics.

    Every derived field must be reproducible from the canonical inputs + the volatility the
    analytics claims it used. Catches a mismatch between reported provenance and the number
    actually produced.
    """
    svc = HistoricalVolatilityService(bar_source=_hpg_source())
    await svc.warm(["HPG"])
    engine = LiveQuantEngine()
    engine.set_historical_vol_getter(svc.get_estimate)

    a, spec = await _compute_reference_analytics(engine)
    await _assert_engine_provenance_consistent(a, spec)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "frozen_date",
    [
        datetime(2026, 6, 1, 10, 0, tzinfo=VN_TZ),   # far from maturity
        datetime(2026, 8, 29, 10, 0, tzinfo=VN_TZ),   # the wall-clock date that first tripped it
        datetime(2026, 9, 5, 10, 0, tzinfo=VN_TZ),    # ~16 days out
        datetime(2026, 9, 18, 15, 30, tzinfo=VN_TZ),  # ~3 days out, greeks most vol-sensitive
    ],
)
async def test_engine_analytics_provenance_is_date_boundary_stable(frozen_vn_now, frozen_date):
    """Regression: the provenance invariant holds regardless of 'today'. The previous
    version reconstructed greeks from model_inputs.time_to_maturity (a 5dp-rounded echo)
    while the engine used full-precision T; as maturity approached, that gap crossed the
    1e-5 tolerance. There is no such gap anymore."""
    frozen_vn_now(frozen_date)

    svc = HistoricalVolatilityService(bar_source=_hpg_source())
    await svc.warm(["HPG"])
    engine = LiveQuantEngine()
    engine.set_historical_vol_getter(svc.get_estimate)

    a, spec = await _compute_reference_analytics(engine)
    assert a.is_available is True
    await _assert_engine_provenance_consistent(a, spec)


@pytest.mark.asyncio
async def test_service_requests_adjusted_daily_closes_from_upstream():
    """At the FiinQuant boundary the service must ask for adjusted=True 1D bars
    (unadjusted closes carry corporate-action jumps that inflate HV)."""
    src = _hpg_source()
    svc = HistoricalVolatilityService(bar_source=src)
    await svc.refresh("HPG")
    assert len(src.calls) == 1
    assert src.calls[0]["adjusted"] is True
    assert src.calls[0]["timeframe"] == "1D"


# --------------------------------------------------------------------------- #
# Application startup resilience
# --------------------------------------------------------------------------- #

def test_startup_survives_hv_warmup_exception(monkeypatch):
    from app.instruments.instrument_registry import instrument_registry

    monkeypatch.setattr(instrument_registry, "get_underlyings", AsyncMock(return_value=["HPG"]))
    monkeypatch.setattr(
        historical_volatility_service, "warm",
        AsyncMock(side_effect=RuntimeError("simulated warm-up failure")),
    )

    with TestClient(app) as c:
        assert c.get("/health").status_code == 200

    # Getter is wired even though warm-up raised; app booted fine.
    assert live_quant_engine._historical_vol_getter is not None


def test_startup_survives_hv_provider_failure(monkeypatch):
    from app.instruments.instrument_registry import instrument_registry
    from app.market_data.market_subscription_manager import subscription_manager

    monkeypatch.setattr(instrument_registry, "get_underlyings", AsyncMock(return_value=["HPG"]))
    monkeypatch.setattr(
        subscription_manager.provider, "get_historical_bars",
        AsyncMock(side_effect=RuntimeError("simulated FiinQuant outage")),
    )

    with TestClient(app) as c:
        assert c.get("/health").status_code == 200

    assert historical_volatility_service.stats()["source_wired"] is True


@pytest.mark.asyncio
async def test_hv_refresh_handles_range_limit_error_without_raising():
    from app.market_data.market_schemas import HistoricalRangeLimitError

    failing = FakeBarSource(fail=True, fail_exc=HistoricalRangeLimitError("Requested range exceeds 365 days limit"))
    svc = HistoricalVolatilityService(bar_source=failing)

    est = await svc.refresh("HPG")
    assert est is None
    assert svc.get_estimate("HPG") is None


@pytest.mark.asyncio
async def test_hv_refresh_handles_auth_error_without_raising():
    from app.market_data.market_schemas import HistoricalAuthError

    failing = FakeBarSource(fail=True, fail_exc=HistoricalAuthError("FiinQuant token expired"))
    svc = HistoricalVolatilityService(bar_source=failing)

    est = await svc.refresh("HPG")
    assert est is None
    assert svc.get_estimate("HPG") is None

