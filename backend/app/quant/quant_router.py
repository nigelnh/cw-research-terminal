"""
REST API Router for Quantitative Analytics & Pricing Engine.
Exposes endpoints for warrant valuation, implied volatility, Greeks, and historical volatility.
"""

import logging
import math
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import settings
from app.instruments.instrument_registry import instrument_registry
from app.quant.quant_schemas import (
    WarrantAnalytics,
    WarrantGreeks,
    HistoricalVolatilityPoint,
    GreeksVolatilitySource,
)
from app.quant.quant_engine import live_quant_engine
from app.quant.black_scholes import (
    calculate_analytical_greeks,
    solve_implied_volatility,
    bs_call_price_share,
)

logger = logging.getLogger(__name__)

quant_router = APIRouter(prefix="/api/quant", tags=["quant"])


class CalculatePricingRequest(BaseModel):
    """Adversarial-input hardened (Step 10): every numeric field rejects NaN/Infinity and
    is bounded. Legitimate supported parameter semantics are unchanged - the bounds are
    far outside any real covered-warrant input."""

    model_config = ConfigDict(populate_by_name=True)

    underlying_price: float = Field(..., alias="underlyingPrice", gt=0, allow_inf_nan=False,
                                    description="Underlying spot price S (VND)")
    strike_price: float = Field(..., alias="strikePrice", gt=0, allow_inf_nan=False,
                                description="Strike price K (VND)")
    time_to_maturity: float = Field(..., alias="timeToMaturity", ge=0, allow_inf_nan=False,
                                    description="Time to maturity T in years")
    risk_free_rate: float = Field(default=0.05, alias="riskFreeRate", ge=-1.0, le=1.0, allow_inf_nan=False,
                                  description="Annual risk-free interest rate r")
    volatility: float = Field(default=0.30, alias="volatility", gt=0, allow_inf_nan=False,
                              description="Volatility sigma (decimal, e.g. 0.30)")
    exercise_ratio: float = Field(default=1.0, alias="exerciseRatio", gt=0, allow_inf_nan=False,
                                  description="Exercise ratio (e.g. 2.0 = 2:1)")
    dividend_yield: float = Field(
        default=0.0, alias="dividendYield", ge=-1.0, le=1.0, allow_inf_nan=False,
        description=(
            "What-if annualized decimal dividend yield q (0.02 = 2%) for THIS stateless "
            "calculation only. The canonical CW analytics engine (GET /api/quant/{symbol}) "
            "always uses q = 0 because HOSE covered warrants are dividend-protected -- see "
            "QUANT_CONTRACT.md section 7."
        ),
    )
    market_price: Optional[float] = Field(
        default=None, alias="marketPrice", ge=0, allow_inf_nan=False,
        description="Optional CW market price to solve IV",
    )

    @model_validator(mode="after")
    def _within_supported_bounds(self) -> "CalculatePricingRequest":
        m = settings
        if self.underlying_price > m.QUANT_CALC_MAX_PRICE or self.strike_price > m.QUANT_CALC_MAX_PRICE:
            raise ValueError("underlyingPrice / strikePrice out of supported range")
        if self.market_price is not None and self.market_price > m.QUANT_CALC_MAX_PRICE:
            raise ValueError("marketPrice out of supported range")
        if self.time_to_maturity > m.QUANT_CALC_MAX_T_YEARS:
            raise ValueError("timeToMaturity out of supported range")
        if self.volatility > m.QUANT_CALC_MAX_SIGMA:
            raise ValueError("volatility out of supported range")
        if self.exercise_ratio > m.QUANT_CALC_MAX_RATIO:
            raise ValueError("exerciseRatio out of supported range")
        for name in ("underlying_price", "strike_price", "time_to_maturity", "risk_free_rate",
                     "volatility", "exercise_ratio", "dividend_yield"):
            v = getattr(self, name)
            if not math.isfinite(v):
                raise ValueError(f"{name} must be a finite number")
        return self


class CalculatePricingResponse(BaseModel):
    theoretical_price: Optional[float] = Field(None, alias="theoreticalPrice")
    delta: Optional[float] = Field(None, alias="delta")
    gamma: Optional[float] = Field(None, alias="gamma")
    theta: Optional[float] = Field(None, alias="theta")
    vega: Optional[float] = Field(None, alias="vega")
    rho: Optional[float] = Field(None, alias="rho")
    implied_volatility: Optional[float] = Field(None, alias="impliedVolatility")


@quant_router.get("/{symbol}", response_model=WarrantAnalytics)
async def get_warrant_analytics(symbol: str):
    """
    Returns quantitative analytics and Greeks for a Covered Warrant symbol.
    """
    sym_upper = symbol.strip().upper()
    if not (1 <= len(sym_upper) <= 32) or not sym_upper.replace(".", "").isalnum():
        raise HTTPException(status_code=400, detail=f"invalid symbol: {symbol!r}")
    analytics = await live_quant_engine.resolve_display_analytics(sym_upper)
    return analytics


@quant_router.post("/calculate", response_model=CalculatePricingResponse)
async def calculate_pricing(req: CalculatePricingRequest):
    """
    Stateless endpoint for Black-Scholes pricing, Greeks, and IV inversion.
    """
    S = req.underlying_price
    K = req.strike_price
    T = req.time_to_maturity
    r = req.risk_free_rate
    q = req.dividend_yield
    sigma = req.volatility
    CR = req.exercise_ratio

    greeks = calculate_analytical_greeks(
        S=S,
        K=K,
        T=T,
        r=r,
        q=q,
        sigma=sigma,
        exercise_ratio=CR,
        volatility_source=GreeksVolatilitySource.HISTORICAL_VOL,
    )

    iv = None
    if req.market_price and req.market_price > 0:
        iv, _ = solve_implied_volatility(
            S=S,
            K=K,
            T=T,
            r=r,
            q=q,
            market_price_cw=req.market_price,
            exercise_ratio=CR,
        )

    return CalculatePricingResponse(
        theoreticalPrice=greeks.theoretical_price,
        delta=greeks.delta,
        gamma=greeks.gamma,
        theta=greeks.theta,
        vega=greeks.vega,
        rho=greeks.rho,
        impliedVolatility=iv,
    )
