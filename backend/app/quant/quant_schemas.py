"""
Canonical Quantitative Analytics & Greeks Schemas for Covered Warrants.
Maintains derived quantitative values distinct from observed vendor market data.
Strictly distinguishes independent Theoretical Fair Price from circular Model Price @ IV Mid.
"""

from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class GreeksVolatilitySource(str, Enum):
    IV_TRADE = "IV_TRADE"
    IV_MID = "IV_MID"
    HISTORICAL_VOL = "HISTORICAL_VOL"
    UNAVAILABLE = "UNAVAILABLE"


class MoneynessCategory(str, Enum):
    ITM = "ITM"
    ATM = "ATM"
    OTM = "OTM"


class ContractLifecycleState(str, Enum):
    """Truthful trading-lifecycle state for the UI. Derived from last_trading_date /
    maturity_date, independent of whether analytics could be computed."""
    ACTIVE = "ACTIVE"                    # tradable, not close to last trading date
    NEAR_EXPIRY = "NEAR_EXPIRY"          # tradable, within QUANT_NEAR_EXPIRY_DAYS of last trading
    LAST_TRADING_DAY = "LAST_TRADING_DAY"  # today is the last trading date
    PENDING_MATURITY = "PENDING_MATURITY"  # past last trading date, not yet matured (NOT tradable)
    EXPIRED = "EXPIRED"                  # past maturity date
    UNKNOWN = "UNKNOWN"                  # dates unavailable


class WarrantGreeks(BaseModel):
    theoretical_price: Optional[float] = Field(
        default=None,
        description="Independent theoretical fair price per warrant in raw VND (evaluated with independent theoretical_volatility, None if unavailable)",
    )
    model_price_at_iv_mid: Optional[float] = Field(
        default=None,
        description="Model price evaluated at IV Mid (reproduces market midpoint by construction, distinct from theoretical fair value)",
    )
    delta: Optional[float] = Field(
        default=None, description="Change in CW price (VND) per +1 VND move in underlying equity"
    )
    gamma: Optional[float] = Field(
        default=None, description="Change in CW Delta per +1 VND move in underlying equity"
    )
    theta: Optional[float] = Field(
        default=None, description="Time decay in CW price (VND) per calendar day (ACT/365)"
    )
    vega: Optional[float] = Field(
        default=None, description="Change in CW price (VND) per +1% (0.01) increase in volatility"
    )
    rho: Optional[float] = Field(
        default=None, description="Change in CW price (VND) per +1% (0.01) increase in risk-free rate"
    )
    volatility_used: Optional[float] = Field(
        default=None, description="Annualized volatility (decimal, e.g. 0.35) used to calculate Greeks"
    )
    volatility_source: GreeksVolatilitySource = Field(
        default=GreeksVolatilitySource.UNAVAILABLE,
        description="Source of volatility used for Greeks calculation (IV_TRADE | IV_MID | HISTORICAL_VOL | UNAVAILABLE)",
    )


class QuantModelInputs(BaseModel):
    underlying_price: Optional[float] = Field(default=None, description="Current underlying spot price S (VND)")
    strike_price: Optional[float] = Field(default=None, description="Effective strike price K (VND)")
    exercise_ratio: Optional[float] = Field(default=None, description="Effective exercise ratio (e.g. 3.5704 = 3.5704:1)")
    time_to_maturity: Optional[float] = Field(default=None, description="Time to maturity T in years (ACT/365)")
    days_to_expiry: Optional[int] = Field(default=None, description="Calendar days to expiry (DTE)")
    risk_free_rate: float = Field(default=0.05, description="Annual risk-free interest rate r (decimal, e.g. 0.05)")
    dividend_yield: float = Field(default=0.0, description="Annualized decimal dividend yield q used for this valuation. Always 0.0 for CW analytics -- HOSE covered warrants are dividend-protected (see QUANT_CONTRACT.md section 7).")
    market_bid: Optional[float] = Field(default=None, description="Market Bid1 price in raw VND")
    market_ask: Optional[float] = Field(default=None, description="Market Ask1 price in raw VND")
    market_last: Optional[float] = Field(default=None, description="Market Last trade price in raw VND")


class HistoricalVolatilityPoint(BaseModel):
    symbol: str
    date: str
    hv22: Optional[float] = None
    hv66: Optional[float] = None
    hv132: Optional[float] = None
    hv252: Optional[float] = None


class WarrantAnalytics(BaseModel):
    symbol: str = Field(..., description="Covered Warrant symbol (e.g. CHPG2602)")
    underlying_symbol: str = Field(..., description="Underlying equity symbol (e.g. HPG)")
    calculated_at: str = Field(..., description="ISO 8601 timestamp of calculation")
    is_available: bool = Field(default=False, description="True if valid inputs allowed analytics computation")
    unavailable_reason: Optional[str] = Field(default=None, description="Diagnostic reason if analytics cannot be computed")

    # Contract trading-lifecycle state (truthful even when is_available is False)
    contract_state: ContractLifecycleState = Field(
        default=ContractLifecycleState.UNKNOWN,
        description="ACTIVE | NEAR_EXPIRY | LAST_TRADING_DAY | PENDING_MATURITY | EXPIRED | UNKNOWN",
    )
    is_tradable: bool = Field(
        default=False,
        description="True only while the warrant can still be traded (ACTIVE / NEAR_EXPIRY / LAST_TRADING_DAY).",
    )

    # Moneyness
    moneyness: Optional[float] = Field(default=None, description="Moneyness ratio S / K")
    moneyness_category: Optional[MoneynessCategory] = Field(default=None, description="ITM | ATM | OTM")

    # Implied Volatilities (decimal, e.g. 0.325 = 32.5%)
    iv_bid: Optional[float] = Field(default=None, description="Implied Volatility solved from real Bid1 price")
    iv_trade: Optional[float] = Field(
        default=None, description="Implied Volatility solved from real Last Match price (None if no trade tick)"
    )
    iv_ask: Optional[float] = Field(default=None, description="Implied Volatility solved from real Ask1 price")
    iv_mid: Optional[float] = Field(default=None, description="Implied Volatility from Bid/Ask midpoint")

    # Historical & Theoretical Volatilities
    historical_volatility: Optional[float] = Field(
        default=None, description="Underlying Historical Volatility (HV_22: 22-session annualized log-return volatility, decimal)"
    )
    theoretical_price: Optional[float] = Field(
        default=None, description="True Theoretical Fair Price evaluated with independent volatility (HV_22)"
    )
    theoretical_volatility: Optional[float] = Field(
        default=None, description="Independent volatility used to compute Theoretical Fair Price (equals HV_22)"
    )
    theoretical_volatility_source: Optional[str] = Field(
        default=None, description="Source of independent theoretical volatility (e.g. HV_22, UNAVAILABLE)"
    )
    model_price_at_iv_mid: Optional[float] = Field(
        default=None, description="Model Price @ IV Mid (reproduced midpoint from market depth, distinct from theoretical fair value)"
    )

    # Theoretical Price & Greeks
    greeks: WarrantGreeks = Field(default_factory=lambda: WarrantGreeks())

    # Model Inputs Snapshot
    model_inputs: Optional[QuantModelInputs] = None
