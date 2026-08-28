import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

# Determine project root (.env location)
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

class Settings(BaseSettings):
    # Application Mode & Ports
    ENVIRONMENT: str = Field(default="development", description="Runtime environment")
    PORT: int = Field(default=8501, description="Backend service port")
    HOST: str = Field(default="0.0.0.0", description="Bind host")

    # AI Service Configuration
    AI_ENABLED: bool = Field(default=True, description="Enable AI research assistant")
    OPENROUTER_API_KEY: str = Field(default="", description="OpenRouter API Key (Server-Side Only)")
    OPENROUTER_MODEL: str = Field(default="stealth/ox-alpha", description="Target OpenRouter model")
    OPENROUTER_BASE_URL: str = Field(default="https://openrouter.ai/api/v1", description="OpenRouter Base URL")
    OPENROUTER_SITE_URL: str = Field(default="https://github.com/nigelnh/cw-research-platform", description="App Site URL header")
    OPENROUTER_APP_NAME: str = Field(default="CW Research Platform", description="App Name header")

    # Request Bounds & Limits
    AI_MAX_MESSAGES: int = Field(default=20, description="Max conversation turns accepted")
    AI_MAX_MESSAGE_LENGTH: int = Field(default=4000, description="Max characters per single message")
    AI_TIMEOUT_SECONDS: float = Field(default=60.0, description="HTTP timeout for AI inference")
    AI_TEMPERATURE: float = Field(default=0.2, description="Sampling temperature for quantitative research")

    # Market Data Provider Configuration (FiinQuant)
    MARKET_DATA_PROVIDER: str = Field(default="fiinquant", description="Active provider: 'fiinquant'")
    FIINQUANT_USERNAME: str = Field(default="", description="FiinQuant account username (server-side only)")
    FIINQUANT_PASSWORD: str = Field(default="", description="FiinQuant account password (server-side only)")
    FIINQUANT_MAX_REALTIME_SYMBOLS: int = Field(default=33, description="Maximum realtime subscription capacity")
    FIINQUANT_ENABLED: bool = Field(default=True, description="Enable live FiinQuant upstream connection")
    FIINQUANT_DEBOUNCE_MS: int = Field(default=300, description="Subscription debounce delay in milliseconds")

    # Redis Warm Market State Cache Configuration
    REDIS_ENABLED: bool = Field(default=True, description="Enable Redis warm market state cache")
    REDIS_URL: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")
    MARKET_STATE_CACHE_TTL_SECONDS: int = Field(default=86400, description="Warm cache key TTL in seconds (24h)")
    MARKET_STATE_MAX_STALENESS_SECONDS: int = Field(default=86400, description="Max acceptable age for restored cached quotes in seconds")

    # Quantitative Engine Configuration
    QUANT_RISK_FREE_RATE: float = Field(default=0.05, description="Default annual risk-free interest rate (5.0%)")
    # NOTE: dividend yield q is NOT configurable. HOSE covered warrants are dividend-protected
    # (strike/ratio adjusted on ex-date), so the CW analytics engine pins q = 0 by convention
    # -- see app.quant.dividend_convention.CW_DIVIDEND_YIELD_CONVENTION and QUANT_CONTRACT.md section 7.
    # The stateless POST /api/quant/calculate endpoint still accepts an arbitrary what-if dividendYield.
    # Historical Volatility (theoretical fair value input).
    # Canonical window = HV_22 (22 trading sessions). Evidence: docs/data_dictionary/warrant_info_columns.md
    # ("Theoretical Price priced at sigma_HV22"), docs/domain/historical_formula_catalog.md F-05 (recovered
    # legacy theo_prc_t.js used sigma_HV22), and the calculate_historical_volatility() primitive default.
    # This is the single authoritative window; no other HV lookback value is defined elsewhere.
    QUANT_HV_WINDOW_SESSIONS: int = Field(default=22, description="Canonical historical volatility window in trading sessions (HV_22)")
    QUANT_HV_MIN_SESSIONS: int = Field(default=10, description="Minimum trading sessions of log-returns required to compute HV")
    QUANT_HV_MAX_STALE_DAYS: int = Field(default=6, description="Max age (VN calendar days) of a cached HV estimate before it is treated as unavailable")
    QUANT_HV_WARMUP_TIMEOUT_SECONDS: float = Field(default=20.0, description="Max seconds to block on HV warm-up during application startup")
    QUANT_HV_REFRESH_INTERVAL_SECONDS: int = Field(default=21600, description="Interval for the background HV refresh loop (default 6h)")
    QUANT_HV_MAX_CONCURRENT_REFRESHES: int = Field(default=4, description="Max concurrent upstream historical fetches during HV refresh")
    QUANT_IV_MAX_ITERATIONS: int = Field(default=100, description="Max iterations for IV root solver")
    QUANT_IV_PRICE_TOLERANCE: float = Field(default=1e-4, description="Price tolerance for IV solver convergence")
    QUANT_IV_SIGMA_TOLERANCE: float = Field(default=1e-4, description="Sigma tolerance for IV solver convergence")
    QUANT_IV_SIGMA_MIN: float = Field(default=1e-4, description="Minimum sigma lower bound (0.01%)")
    QUANT_IV_SIGMA_MAX: float = Field(default=5.0, description="Maximum sigma upper bound (500%)")

    model_config = SettingsConfigDict(
        env_file=(
            str(PROJECT_ROOT / ".env"),
            str(BACKEND_DIR / ".env"),
            str(BACKEND_DIR / "poc" / "fiinquant" / ".env"),
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()
