"""Single coherent production-config validation boundary.

Called once during application startup. When ``ENVIRONMENT != production`` it is a no-op
(local dev stays convenient). When ``ENVIRONMENT == production`` it collects every
blocking misconfiguration and, if any exist, raises :class:`ProductionConfigError` so the
process fails fast and loudly rather than serving with an unsafe posture.

It only enforces configuration for features that are actually enabled - a disabled
optional feature is never required.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("cw-research-backend.security")


class ProductionConfigError(RuntimeError):
    """One or more blocking production misconfigurations."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        joined = "\n  - ".join(problems)
        super().__init__(f"Refusing to start in production with unsafe configuration:\n  - {joined}")


def collect_production_problems(settings, *, rate_limiter_mode: str | None = None) -> list[str]:
    """Return the list of blocking problems (empty unless production)."""
    if not settings.is_production():
        return []

    p: list[str] = []

    # ---- CORS ----
    origins = settings.cors_allowed_origins()
    if not settings.CORS_ALLOWED_ORIGINS.strip():
        p.append("CORS_ALLOWED_ORIGINS is empty - browser clients will be blocked. Set explicit origin(s).")
    if "*" in origins:
        p.append("CORS_ALLOWED_ORIGINS contains '*'. A wildcard origin with credentials is unsafe; list exact origins.")

    # ---- Host header ----
    hosts = settings.allowed_hosts()
    if not settings.ALLOWED_HOSTS.strip():
        p.append("ALLOWED_HOSTS is empty - the Host header is not enforced. Set the API hostname(s).")
    elif "*" in hosts:
        p.append("ALLOWED_HOSTS contains '*' - the Host header is effectively unenforced.")

    # ---- Rate limiter (only when enabled) ----
    if settings.PUBLIC_RATE_LIMIT_ENABLED:
        backend = (settings.RATE_LIMIT_BACKEND or "auto").strip().lower()
        allow_single = settings.ALLOW_SINGLE_PROCESS_RATE_LIMIT
        if backend == "memory" and not allow_single:
            p.append(
                "RATE_LIMIT_BACKEND=memory in production. Per-process limits are not shared across "
                "workers. Use redis, or set ALLOW_SINGLE_PROCESS_RATE_LIMIT=true for a single-worker demo."
            )
        if backend == "redis" and not settings.rate_limit_redis_url():
            p.append("RATE_LIMIT_BACKEND=redis but no Redis URL (RATE_LIMIT_REDIS_URL / REDIS_URL).")
        if backend == "auto" and not (settings.REDIS_ENABLED and settings.rate_limit_redis_url()) and not allow_single:
            p.append(
                "RATE_LIMIT_BACKEND=auto in production with no reachable Redis config - it would fall back "
                "to a per-process limiter. Configure Redis or set ALLOW_SINGLE_PROCESS_RATE_LIMIT=true."
            )
        if rate_limiter_mode == "memory" and backend in ("redis", "auto") and not allow_single:
            p.append(
                "The rate limiter is running on in-process memory in production (Redis unreachable at "
                "startup). Fix Redis or set ALLOW_SINGLE_PROCESS_RATE_LIMIT=true."
            )
    else:
        p.append("PUBLIC_RATE_LIMIT_ENABLED=false in production - the public API has no rate limiting.")

    # ---- Trusted proxy ----
    if settings.RATE_LIMIT_TRUST_PROXY and not settings.trusted_proxy_cidrs():
        p.append(
            "RATE_LIMIT_TRUST_PROXY=true but TRUSTED_PROXY_CIDRS is empty - X-Forwarded-For would be "
            "honored from every peer. Set the reverse-proxy network CIDR(s)."
        )

    # ---- Database (only when enabled) ----
    if settings.DATABASE_ENABLED and not settings.DATABASE_URL.strip():
        p.append("DATABASE_ENABLED=true but DATABASE_URL is empty.")

    # ---- Auth (only when a protected surface is intentionally enabled) ----
    if settings.auth_configured():
        if settings.SUPABASE_URL.strip() and not settings.supabase_jwks_url():
            p.append("SUPABASE_URL is set but a JWKS URL could not be derived - check SUPABASE_URL.")
        if not settings.SUPABASE_URL.strip() and not settings.SUPABASE_JWT_SECRET.strip():
            p.append("Auth appears enabled but neither SUPABASE_URL nor SUPABASE_JWT_SECRET is set.")
    if settings.AUTH_TEST_HS256_SECRET.strip():
        p.append("AUTH_TEST_HS256_SECRET is set in production. It is ignored at runtime, but must not be present.")

    # ---- AI provider key (only when public AI is on) ----
    if settings.AI_ENABLED and settings.AI_PUBLIC_ENABLED and not settings.OPENROUTER_API_KEY.strip():
        p.append("AI_ENABLED and AI_PUBLIC_ENABLED are true but OPENROUTER_API_KEY is empty. Set the key or disable public AI.")

    # ---- HSTS: a deployment choice, never required here ----
    if settings.SECURITY_HSTS_ENABLED:
        logger.info("SECURITY_HSTS_ENABLED=true - ensure the deployment terminates TLS end-to-end.")

    return p


def enforce_production_config(settings, *, rate_limiter_mode: str | None = None) -> None:
    problems = collect_production_problems(settings, rate_limiter_mode=rate_limiter_mode)
    if problems:
        raise ProductionConfigError(problems)
