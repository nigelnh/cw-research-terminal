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
    OPENROUTER_SITE_URL: str = Field(default="https://github.com/nigelnh/cw-research-terminal", description="App Site URL header")
    OPENROUTER_APP_NAME: str = Field(default="CW Research Terminal", description="App Name header")

    # Request Bounds & Limits
    AI_MAX_MESSAGES: int = Field(default=20, description="Max conversation turns accepted")
    AI_MAX_MESSAGE_LENGTH: int = Field(default=4000, description="Max characters per single message")
    AI_TIMEOUT_SECONDS: float = Field(default=60.0, description="HTTP timeout for AI inference")
    AI_TEMPERATURE: float = Field(default=0.2, description="Sampling temperature for quantitative research")
    AI_HISTORY_MAX_LOOKBACK_DAYS: int = Field(default=120, description="Max calendar span the AI get_history tool may request")
    AI_HISTORY_MAX_POINTS: int = Field(default=60, description="Max OHLCV rows the AI get_history tool returns (older rows downsampled)")

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
    # Moneyness (S/K) categorical band for the UI label ONLY. The raw numeric moneyness is
    # always reported unrounded-by-category; this tolerance around parity (1.0) decides the
    # ITM / ATM / OTM label. 0.03 = classify |S/K - 1| <= 3% as ATM. Does not touch BSM inputs.
    QUANT_MONEYNESS_ATM_BAND: float = Field(default=0.03, description="Half-width of the ATM band around S/K = 1.0 for the categorical label")
    # A CW contract record is only allowed to gate analytics as VERIFIED_CURRENT while its
    # provenance is fresh. Past this age (VN calendar days since the provenance retrieved_at)
    # a VERIFIED_CURRENT record is downgraded to STALE at load time and the quant gate rejects
    # it until the metadata is re-reconciled. Set generously: contract terms change rarely.
    INSTRUMENT_METADATA_MAX_AGE_DAYS: int = Field(default=120, description="Max age of CW metadata provenance before VERIFIED_CURRENT auto-downgrades to STALE")
    QUANT_NEAR_EXPIRY_DAYS: int = Field(default=10, description="Calendar days before last-trading-date at which a CW's contract_state becomes NEAR_EXPIRY")
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

    # ------------------------------------------------------------------ #
    # Authentication (Step 9) - Supabase Auth as the identity provider    #
    # ------------------------------------------------------------------ #
    # The backend NEVER issues sessions or stores passwords. It only VERIFIES the access
    # token minted by Supabase for requests to the protected /api/me/* namespace. All public
    # market-data / quant / history / websocket routes stay anonymous.
    #
    # Two verification modes, auto-selected:
    #   - asymmetric (preferred): SUPABASE_URL is set -> fetch + cache the project JWKS at
    #     {SUPABASE_URL}/auth/v1/.well-known/jwks.json, verify RS256/ES256 by `kid`.
    #   - shared-secret (legacy): SUPABASE_JWT_SECRET is set -> verify HS256 locally.
    # If BOTH are set, whichever matches the token's `alg` header is used.
    SUPABASE_URL: str = Field(
        default="",
        description="Supabase project URL, e.g. https://abcxyz.supabase.co (used to derive issuer + JWKS URL)",
    )
    SUPABASE_JWT_SECRET: str = Field(
        default="",
        description="Legacy HS256 JWT signing secret from the Supabase dashboard (server-side only). Optional when SUPABASE_URL is set.",
    )
    SUPABASE_JWT_AUDIENCE: str = Field(
        default="authenticated",
        description="Expected `aud` claim on Supabase user access tokens",
    )
    SUPABASE_JWT_ISSUER: str = Field(
        default="",
        description="Expected `iss` claim. Empty -> derived as {SUPABASE_URL}/auth/v1",
    )
    SUPABASE_JWKS_URL: str = Field(
        default="",
        description="Override for the JWKS endpoint. Empty -> derived as {SUPABASE_URL}/auth/v1/.well-known/jwks.json",
    )
    SUPABASE_JWKS_CACHE_SECONDS: int = Field(
        default=600, description="How long a fetched JWKS key set is reused before refetch"
    )
    AUTH_JWT_LEEWAY_SECONDS: int = Field(
        default=30, description="Clock-skew leeway applied to exp/nbf/iat verification"
    )

    # Per-user primary watchlist (the one user-owned feature in Step 9).
    ME_WATCHLIST_MAX_ITEMS: int = Field(
        default=50, description="Hard cap on symbols in a user's persisted primary watchlist"
    )

    # TEST-ONLY escape hatch: when set to a non-empty value AND ENVIRONMENT != 'production',
    # the JWT verifier accepts HS256 tokens signed with this secret. Used exclusively by the
    # automated test-suite so no live Supabase project is needed. It is IGNORED in production
    # regardless of value (see app.auth.jwt_verifier). Never set this in a deployed env.
    AUTH_TEST_HS256_SECRET: str = Field(
        default="",
        description="TEST ONLY. Accept HS256 tokens signed with this secret. Ignored when ENVIRONMENT=production.",
    )

    def auth_configured(self) -> bool:
        """True when the backend has enough config to verify real Supabase tokens."""
        return bool(self.SUPABASE_URL.strip() or self.SUPABASE_JWT_SECRET.strip())

    def supabase_issuer(self) -> str:
        if self.SUPABASE_JWT_ISSUER.strip():
            return self.SUPABASE_JWT_ISSUER.strip()
        base = self.SUPABASE_URL.strip().rstrip("/")
        return f"{base}/auth/v1" if base else ""

    def supabase_jwks_url(self) -> str:
        if self.SUPABASE_JWKS_URL.strip():
            return self.SUPABASE_JWKS_URL.strip()
        base = self.SUPABASE_URL.strip().rstrip("/")
        return f"{base}/auth/v1/.well-known/jwks.json" if base else ""

    def auth_test_secret_active(self) -> str:
        """The test HS256 secret, or '' when it must not be honored (production)."""
        if self.ENVIRONMENT.strip().lower() == "production":
            return ""
        return self.AUTH_TEST_HS256_SECRET.strip()

    # ================================================================== #
    # Step 10 - Public API abuse / cost / deployment-safety hardening      #
    # ================================================================== #
    # None of this changes the public product surface: the dashboard, research,
    # market/quant/history reads and the websocket stay anonymous. These knobs bound
    # *rate*, *size*, *concurrency* and *cost*, and make deployment defaults safe.

    # ---- master switches -------------------------------------------------
    PUBLIC_RATE_LIMIT_ENABLED: bool = Field(
        default=True, description="Master switch for HTTP rate limiting (disable only for debugging)"
    )
    AI_PUBLIC_ENABLED: bool = Field(
        default=True, description="Allow anonymous access to /api/ai/*. When false the endpoint 503s cleanly."
    )
    PUBLIC_REALTIME_ENABLED: bool = Field(
        default=True, description="Allow public /ws/market connections. When false the upgrade is refused."
    )
    SECURITY_HEADERS_ENABLED: bool = Field(default=True, description="Attach API security headers to responses")
    SECURITY_HSTS_ENABLED: bool = Field(
        default=False,
        description="Send Strict-Transport-Security. ONLY enable when the deployment is HTTPS end-to-end.",
    )

    # ---- rate-limit backend -------------------------------------------------
    # auto   : Redis when REDIS_ENABLED and a URL resolves, else in-process memory
    # memory : always in-process (single worker); fine for local/CI and small demos
    # redis  : always Redis; startup validates a URL is configured
    RATE_LIMIT_BACKEND: str = Field(default="auto", description="auto | memory | redis")
    RATE_LIMIT_REDIS_URL: str = Field(
        default="", description="Override Redis URL for the limiter. Empty -> reuse REDIS_URL."
    )
    RATE_LIMIT_FAIL_OPEN: bool = Field(
        default=False,
        description="If the Redis limiter errors: false -> fall back to a conservative in-process limiter "
        "(never unlimited); true -> allow the request. AI is always fail-closed regardless.",
    )
    ALLOW_SINGLE_PROCESS_RATE_LIMIT: bool = Field(
        default=False,
        description="DEMO/SINGLE-WORKER ONLY. Permit a per-process memory rate limiter when "
        "ENVIRONMENT=production. Limits are NOT shared across workers - safe ONLY for a "
        "single-worker deployment. Without this, production requires a working Redis limiter "
        "and fails startup otherwise.",
    )

    # ---- trusted proxy / client-IP ---------------------------------------
    # The client IP is used ONLY as a rate-limit key. Three ingress modes:
    #   direct  - the socket peer; forwarded headers are ignored entirely (local/dev,
    #             or any deployment where the app is the edge).
    #   cidr    - walk X-Forwarded-For, but ONLY when the direct peer is inside
    #             TRUSTED_PROXY_CIDRS (a generic, self-managed reverse proxy).
    #   railway - trust ONLY the left-most X-Forwarded-For entry, and ONLY when
    #             ENVIRONMENT=production AND the process is running on a verified
    #             Railway service (RAILWAY_* injected env). Railway's edge strips and
    #             re-writes XFF so the left-most entry is the real client; its
    #             X-Real-IP is unreliable behind the CDN and is never read. Deploy the
    #             Railway service with CDN/edge caching DISABLED.
    # Empty -> 'cidr' when RATE_LIMIT_TRUST_PROXY is true, else 'direct' (back-compat).
    CLIENT_IP_TRUST_MODE: str = Field(
        default="",
        description="Client-IP ingress mode: direct | cidr | railway. Empty -> cidr if "
        "RATE_LIMIT_TRUST_PROXY else direct.",
    )
    RATE_LIMIT_TRUST_PROXY: bool = Field(
        default=False,
        description="Legacy switch for 'cidr' mode: honor X-Forwarded-For ONLY when the direct peer is "
        "in TRUSTED_PROXY_CIDRS. Prefer CLIENT_IP_TRUST_MODE. Keep false for direct local dev.",
    )
    TRUSTED_PROXY_CIDRS: str = Field(
        default="",
        description="'cidr' mode: comma-separated CIDRs of trusted reverse proxies "
        "(e.g. '10.0.0.0/8,127.0.0.1/32'). XFF from any other direct peer is ignored.",
    )

    # ---- per-tier HTTP policies (requests / window seconds), keyed per client ----
    RL_HEALTH_PER_MIN: int = Field(default=120, description="Tier A: /health, /api/*/health, small metadata")
    RL_MARKET_PER_MIN: int = Field(default=120, description="Tier B: ordinary market-data + instrument reads")
    RL_QUANT_PER_MIN: int = Field(default=40, description="Tier C: /api/quant/* (CPU-bounded, body-bounded)")
    RL_HISTORY_PER_MIN: int = Field(default=20, description="Tier D: /api/market/history/* (DB + possible provider fill)")
    RL_AI_PER_MIN: int = Field(default=6, description="Tier E burst: /api/ai/* per minute (spends real money)")
    RL_AI_PER_HOUR: int = Field(default=40, description="Tier E sustained: /api/ai/* per hour")
    RL_ME_PER_MIN: int = Field(default=30, description="Tier F: authenticated /api/me/* (keyed by verified sub)")
    RL_DEFAULT_PER_MIN: int = Field(default=60, description="Catch-all for any public route without a specific tier")

    # ---- request body size (bytes) -------------------------------------
    API_MAX_BODY_BYTES: int = Field(
        default=64 * 1024, description="Max JSON body for quant / watchlist / reconcile (64 KiB)"
    )
    AI_MAX_BODY_BYTES: int = Field(
        default=256 * 1024, description="Max body for /api/ai/* (conversation history + context) (256 KiB)"
    )

    # ---- AI cost controls -------------------------------------------------
    AI_MAX_INPUT_CHARS: int = Field(
        default=12000, description="Max total characters across all messages in one /api/ai/chat request"
    )
    AI_MAX_CONCURRENT: int = Field(default=3, description="Max in-flight upstream AI calls across the whole process")
    AI_MAX_OUTPUT_TOKENS: int = Field(default=1024, description="max_tokens sent to the AI provider (bounds output cost)")
    AI_ACQUIRE_TIMEOUT_SECONDS: float = Field(
        default=5.0, description="Max wait for an AI concurrency slot before returning 503"
    )
    AI_DAILY_REQUEST_BUDGET: int = Field(
        default=0,
        description="If > 0, a process-local per-UTC-day cap on total AI requests (single-worker only). 0 disables.",
    )

    # ---- history HTTP-layer protection (separate from ingestion throttling) ----
    HISTORY_MAX_CONCURRENT_GAPFILLS: int = Field(
        default=2, description="Max distinct history streams triggering a provider gap-fill at once (HTTP layer)"
    )

    # ---- instrument reconcile input bound -------------------------------
    INSTRUMENTS_RECONCILE_MAX_SYMBOLS: int = Field(
        default=5000, description="Max symbols accepted by POST /api/instruments/reconcile"
    )

    # ---- quant /calculate adversarial-input bounds --------------------
    QUANT_CALC_MAX_PRICE: float = Field(default=1e12, description="Upper bound for S / K / marketPrice (raw VND)")
    QUANT_CALC_MAX_T_YEARS: float = Field(default=100.0, description="Upper bound for timeToMaturity")
    QUANT_CALC_MAX_SIGMA: float = Field(default=50.0, description="Upper bound for volatility sigma (5000%)")
    QUANT_CALC_MAX_RATIO: float = Field(default=1e6, description="Upper bound for exerciseRatio")

    # ---- websocket protection ------------------------------------------
    WS_MAX_CONNECTIONS_TOTAL: int = Field(default=200, description="Global ceiling on concurrent /ws/market clients")
    WS_MAX_CONNECTIONS_PER_IP: int = Field(default=8, description="Max concurrent /ws/market connections from one client key")
    WS_MAX_SYMBOLS_PER_CLIENT: int = Field(
        default=40,
        description="Structural cap on symbols in one subscribe frame. The provider still enforces "
        "FIINQUANT_MAX_REALTIME_SYMBOLS as the true realtime capacity.",
    )
    WS_MAX_MESSAGE_BYTES: int = Field(default=16 * 1024, description="Max size of one inbound websocket text frame")
    WS_MESSAGE_BURST: int = Field(default=30, description="Max inbound messages per WS_MESSAGE_WINDOW_SECONDS per connection")
    WS_MESSAGE_WINDOW_SECONDS: float = Field(default=10.0, description="Sliding window for WS_MESSAGE_BURST")
    WS_IDLE_TIMEOUT_SECONDS: float = Field(
        default=300.0, description="Close a /ws/market connection that sends nothing for this long"
    )

    # ---- CORS / host policy -------------------------------------------
    CORS_ALLOWED_ORIGINS: str = Field(
        default="",
        description="Comma-separated exact frontend origins. Empty in development -> localhost dev origins. "
        "REQUIRED (non-empty) in production. '*' is never combined with credentials.",
    )
    ALLOWED_HOSTS: str = Field(
        default="",
        description="Comma-separated allowed Host headers. Empty -> not enforced (dev). Set explicitly in production.",
    )

    # ---- outbound timeouts (seconds) ---------------------------------
    JWKS_FETCH_TIMEOUT_SECONDS: float = Field(default=5.0, description="Timeout for the Supabase JWKS fetch")

    # ------------------------------------------------------------------ derived helpers

    def is_production(self) -> bool:
        return self.ENVIRONMENT.strip().lower() == "production"

    def rate_limit_redis_url(self) -> str:
        return (self.RATE_LIMIT_REDIS_URL or self.REDIS_URL or "").strip()

    def trusted_proxy_cidrs(self) -> list[str]:
        return [c.strip() for c in self.TRUSTED_PROXY_CIDRS.split(",") if c.strip()]

    def client_ip_trust_mode(self) -> str:
        """Resolved client-IP ingress mode: 'direct' | 'cidr' | 'railway'."""
        m = (self.CLIENT_IP_TRUST_MODE or "").strip().lower()
        if m in ("direct", "cidr", "railway"):
            return m
        return "cidr" if self.RATE_LIMIT_TRUST_PROXY else "direct"

    def cors_allowed_origins(self) -> list[str]:
        explicit = [o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
        if explicit:
            return explicit
        if self.is_production():
            return []  # must be configured; startup will warn
        return [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]

    def allowed_hosts(self) -> list[str]:
        hosts = [h.strip() for h in self.ALLOWED_HOSTS.split(",") if h.strip()]
        return hosts or ["*"]

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

    def async_database_url(self) -> str:
        """The async (asyncpg) form of DATABASE_URL. Managed Postgres providers (Railway,
        Heroku, Render, ...) hand out a bare ``postgresql://`` / ``postgres://`` URL; the
        async engine needs the ``+asyncpg`` driver spelled out."""
        url = self.DATABASE_URL
        if url.startswith("postgresql+asyncpg://"):
            return url
        if url.startswith("postgresql+psycopg2://"):
            return "postgresql+asyncpg://" + url[len("postgresql+psycopg2://"):]
        if url.startswith("postgres://"):
            return "postgresql+asyncpg://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            return "postgresql+asyncpg://" + url[len("postgresql://"):]
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
