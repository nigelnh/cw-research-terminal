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
    # Live analytics scheduler: max Covered Warrants whose analytics may be recomputed concurrently.
    # Per-symbol work is already single-flighted; this bounds the global fan-out.
    QUANT_MAX_CONCURRENT_COMPUTES: int = Field(default=8, description="Max concurrent live CW analytics recomputations")
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

    # ------------------------------------------------------------------ #
    # Durable Historical Market-Data Persistence (PostgreSQL)             #
    # ------------------------------------------------------------------ #
    # OFF by default: the realtime market path and every existing test boot
    # unchanged when DATABASE_ENABLED is false. This is storage foundation only;
    # the public historical API still serves from FiinQuant until Step 7.
    DATABASE_ENABLED: bool = Field(default=False, description="Enable the PostgreSQL persistence layer")
    DATABASE_URL: str = Field(
        default="",
        description="Async SQLAlchemy URL, e.g. postgresql+asyncpg://user:pass@host:5432/cw_research (server-side only)",
    )
    DATABASE_REQUIRE_ON_STARTUP: bool = Field(
        default=False,
        description="If true and DATABASE_ENABLED, a failed DB connection aborts application startup instead of degrading",
    )
    DATABASE_POOL_SIZE: int = Field(default=5, description="SQLAlchemy async engine connection pool size")
    DATABASE_MAX_OVERFLOW: int = Field(default=5, description="Extra connections allowed beyond the pool size under load")
    DATABASE_POOL_TIMEOUT_SECONDS: float = Field(default=10.0, description="Seconds to wait for a pooled connection before erroring")
    DATABASE_POOL_RECYCLE_SECONDS: int = Field(default=1800, description="Recycle pooled connections older than this (hosted PG idle cutoffs)")
    DATABASE_STATEMENT_TIMEOUT_MS: int = Field(default=30000, description="Per-statement timeout applied to every DB session (0 disables)")
    DATABASE_ECHO_SQL: bool = Field(default=False, description="Log every emitted SQL statement (debug only)")
    DATABASE_BULK_CHUNK_SIZE: int = Field(default=5000, description="Rows per INSERT ... ON CONFLICT statement during bulk bar upserts")

    # ------------------------------------------------------------------ #
    # Historical ingestion (Step 6) - resumable, quota-safe FiinQuant backfill  #
    # ------------------------------------------------------------------ #
    # Conservative by design: predictable + resumable + quota-safe, NOT fastest.
    # Empirically verified (2026-08): this FiinQuant account has a ~1-year historical
    # LOOKBACK entitlement. A ~355-day request span with small lookback returns 200;
    # any window whose oldest date is >~365 days old returns HTTP 403. Request *span*
    # up to ~355 days is fine.
    INGEST_MAX_LOOKBACK_DAYS: int = Field(
        default=360,
        description="Oldest date a historical request may reach back to (account entitlement ~1 year; keep < 365)",
    )
    INGEST_MAX_CHUNK_SPAN_DAYS: int = Field(
        default=350,
        description="Maximum span of a single provider request window in calendar days (safely inside the observed ~355)",
    )
    INGEST_MAX_CONCURRENT_REQUESTS: int = Field(
        default=1,
        description="Bounded worker pool size for concurrent historical provider requests "
        "(1 = fully serial; FiinQuant rate-limits aggressive parallel historical fetches)",
    )
    INGEST_MIN_REQUEST_INTERVAL_SECONDS: float = Field(
        default=2.0,
        description="Minimum delay between successive provider requests (global throttle)",
    )
    INGEST_MAX_RETRIES: int = Field(default=5, description="Max retry attempts for a retryable provider error")
    INGEST_RETRY_BASE_SECONDS: float = Field(default=2.0, description="Base delay for exponential backoff")
    INGEST_RETRY_MAX_SECONDS: float = Field(default=60.0, description="Ceiling for a single backoff sleep")
    INGEST_MAX_SYMBOLS_PER_INVOCATION: int = Field(
        default=60,
        description="Refuse a single CLI invocation targeting more symbols than this (quota guardrail)",
    )
    INGEST_INCREMENTAL_OVERLAP_DAYS_1D: int = Field(
        default=5, description="Calendar-day re-fetch overlap for daily incremental sync (vendor EOD revision window)"
    )
    INGEST_INCREMENTAL_OVERLAP_DAYS_INTRADAY: int = Field(
        default=2, description="Calendar-day re-fetch overlap for intraday incremental sync"
    )
    INGEST_ADVISORY_LOCK_NAMESPACE: int = Field(
        default=0x43574947,  # 'CWIG'
        description="First key of the PostgreSQL two-int advisory lock used to serialise ingestion of one logical stream",
    )
    INGEST_SOURCE_LABEL: str = Field(default="fiinquant", description="`source` value written to market_bars / ingestion_* rows")

    # ------------------------------------------------------------------ #
    # Historical read path (Step 7) - PostgreSQL-first reads for /api/market/history  #
    # ------------------------------------------------------------------ #
    # auto           : postgres_first when DATABASE_ENABLED and the DB is reachable, else provider_direct
    # postgres_first : always read PostgreSQL first, controlled gap-fill from the provider
    # provider_direct: legacy behavior - every request goes straight to the provider (dev / DB off)
    HISTORY_SOURCE_MODE: str = Field(
        default="auto", description="Historical read mode: auto | postgres_first | provider_direct"
    )
    # PostgreSQL-first applies only to daily bars; other timeframes stay provider-direct
    # (no intraday history is persisted yet).
    HISTORY_POSTGRES_TIMEFRAMES: str = Field(
        default="1d", description="Comma-separated timeframes served PostgreSQL-first (others go provider-direct)"
    )
    HISTORY_GAPFILL_ENABLED: bool = Field(
        default=True, description="Allow the read path to trigger a controlled provider gap-fill for a missing in-horizon range"
    )
    HISTORY_GAPFILL_LOCK_WAIT_SECONDS: float = Field(
        default=25.0,
        description="Max seconds a concurrent cache-miss waits on the per-stream fill lock before serving the current DB result",
    )
    HISTORY_GAPFILL_FAILURE_COOLDOWN_SECONDS: float = Field(
        default=120.0,
        description="After a failed gap-fill for a stream, suppress further fill attempts for this long (thundering-herd guard)",
    )
    HISTORY_DEFAULT_LOOKBACK_DAYS: int = Field(
        default=400, description="Default requested span (days back from today) when from_date/to_date are omitted"
    )
    HISTORY_MAX_RANGE_DAYS: int = Field(
        default=1500,
        description="Hard cap on the calendar span of a single /api/market/history request (~4y; PG may hold more than the 360d provider horizon)",
    )
    HISTORY_MAX_RESULT_BARS: int = Field(
        default=6000, description="Hard cap on rows returned by a single /api/market/history request"
    )
    # Historical Volatility source: when DATABASE_ENABLED, HV reads PostgreSQL via
    # PostgresHistoricalBarSource. If a symbol has fewer than this many persisted adjusted
    # daily bars, a controlled off-tick gap-fill is triggered (never inside LiveQuantEngine).
    HV_POSTGRES_MIN_BARS_FOR_FILL: int = Field(
        default=40, description="Minimum persisted daily bars before HV triggers a controlled provider fill for a symbol"
    )

    def history_postgres_timeframes(self) -> set[str]:
        return {t.strip().lower() for t in self.HISTORY_POSTGRES_TIMEFRAMES.split(",") if t.strip()}

    def sync_database_url(self) -> str:
        """The synchronous (psycopg2) form of DATABASE_URL, used by Alembic migrations."""
        url = self.DATABASE_URL
        if url.startswith("postgresql+asyncpg://"):
            return "postgresql+psycopg2://" + url[len("postgresql+asyncpg://"):]
        if url.startswith("postgres://"):
            return "postgresql+psycopg2://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            return "postgresql+psycopg2://" + url[len("postgresql://"):]
        return url

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
