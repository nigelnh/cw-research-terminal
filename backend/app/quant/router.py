"""
REST API Router for Quantitative Analytics & Pricing Engine.
Exposes endpoints for warrant valuation, implied volatility, Greeks, and historical volatility.
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import settings
from app.instruments.registry import instrument_registry
from app.quant.schemas import (
    WarrantAnalytics,
    WarrantGreeks,
    HistoricalVolatilityPoint,
    GreeksVolatilitySource,
)
from app.quant.engine import live_quant_engine
from app.quant.black_scholes import (
    calculate_analytical_greeks,
    solve_implied_volatility,
    bs_call_price_share,
)

logger = logging.getLogger(__name__)

quant_router = APIRouter(prefix="/api/quant", tags=["quant"])


class CalculatePricingRequest(BaseModel):
    underlying_price: float = Field(..., alias="underlyingPrice", description="Underlying spot price S (VND)")
    strike_price: float = Field(..., alias="strikePrice", description="Strike price K (VND)")
    time_to_maturity: float = Field(..., alias="timeToMaturity", description="Time to maturity T in years")
    risk_free_rate: float = Field(
        default=0.05, alias="riskFreeRate", description="Annual risk-free interest rate r"
    )
    volatility: float = Field(
        default=0.30, alias="volatility", description="Volatility sigma (decimal, e.g. 0.30)"
    )
    exercise_ratio: float = Field(
        default=1.0, alias="exerciseRatio", description="Exercise ratio (e.g. 2.0 = 2:1)"
    )
    dividend_yield: float = Field(
        default=0.0, alias="dividendYield", description="Dividend yield assumption q"
    )
    market_price: Optional[float] = Field(
        default=None, alias="marketPrice", description="Optional CW market price to solve IV"
    )


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
    analytics = await live_quant_engine.compute_warrant_analytics(sym_upper)
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
