"""Production fail-safe: rate-limiter startup policy + config validation boundary (Step 11 prep §5, §6)."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.production_guard import (
    ProductionConfigError,
    collect_production_problems,
    enforce_production_config,
)
from app.security.rate_limiter import RateLimiter, RateLimiterStartupError

_UNREACHABLE = "redis://127.0.0.1:1/0"
_aio = pytest.mark.asyncio


def _prod(monkeypatch, **overrides):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "PUBLIC_RATE_LIMIT_ENABLED", True)
    for k, v in overrides.items():
        monkeypatch.setattr(settings, k, v)


# --------------------- rate limiter startup fail-safe ---------------------

@_aio
async def test_dev_keeps_convenient_memory_fallback(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setattr(settings, "RATE_LIMIT_REDIS_URL", _UNREACHABLE)
    rl = RateLimiter()
    await rl.configure()  # does NOT raise in dev
    assert rl.mode == "memory"


@_aio
async def test_prod_redis_unreachable_fails_startup(monkeypatch):
    _prod(monkeypatch, RATE_LIMIT_BACKEND="redis", RATE_LIMIT_REDIS_URL=_UNREACHABLE, REDIS_ENABLED=True)
    with pytest.raises(RateLimiterStartupError):
        await RateLimiter().configure()


@_aio
async def test_prod_memory_backend_rejected_without_override(monkeypatch):
    _prod(monkeypatch, RATE_LIMIT_BACKEND="memory", ALLOW_SINGLE_PROCESS_RATE_LIMIT=False)
    with pytest.raises(RateLimiterStartupError):
        await RateLimiter().configure()


@_aio
async def test_prod_memory_backend_allowed_with_explicit_override(monkeypatch):
    _prod(monkeypatch, RATE_LIMIT_BACKEND="memory", ALLOW_SINGLE_PROCESS_RATE_LIMIT=True)
    rl = RateLimiter()
    await rl.configure()
    assert rl.mode == "memory"


@_aio
async def test_prod_auto_without_redis_fails_startup(monkeypatch):
    _prod(monkeypatch, RATE_LIMIT_BACKEND="auto", REDIS_ENABLED=False, RATE_LIMIT_REDIS_URL="",
          ALLOW_SINGLE_PROCESS_RATE_LIMIT=False)
    with pytest.raises(RateLimiterStartupError):
        await RateLimiter().configure()


@_aio
async def test_prod_redis_reachable_configures_cleanly(monkeypatch):
    _prod(monkeypatch, RATE_LIMIT_BACKEND="redis", RATE_LIMIT_REDIS_URL="redis://localhost:6379/0", REDIS_ENABLED=True)
    rl = RateLimiter()
    try:
        await rl.configure()
    except RateLimiterStartupError:
        pytest.skip("local redis not available")
    assert rl.mode == "redis"
    await rl.reset()


@_aio
async def test_ai_fail_closed_still_denies_on_backend_error(monkeypatch):
    """The production fail-safe changes must not weaken AI cost protection."""
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "memory")
    rl = RateLimiter()
    await rl.configure()

    async def boom(*a, **k):
        raise RuntimeError("redis gone")

    monkeypatch.setattr(rl._primary, "hit", boom)
    from app.security.rate_limiter import per_minute

    d = await rl.check(tier="ai", key="ip:x", items=(per_minute(100),), fail_closed=True)
    assert not d.allowed


# --------------------- production config validation ---------------------

def test_dev_has_no_problems(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    assert collect_production_problems(settings) == []


def test_bare_production_flags_cors_and_hosts(monkeypatch):
    _prod(monkeypatch, CORS_ALLOWED_ORIGINS="", ALLOWED_HOSTS="")
    probs = collect_production_problems(settings, rate_limiter_mode="redis")
    joined = " ".join(probs)
    assert "CORS_ALLOWED_ORIGINS" in joined
    assert "ALLOWED_HOSTS" in joined


def test_dangerous_combinations_flagged(monkeypatch):
    _prod(monkeypatch, CORS_ALLOWED_ORIGINS="*", ALLOWED_HOSTS="*",
          RATE_LIMIT_TRUST_PROXY=True, TRUSTED_PROXY_CIDRS="")
    joined = " ".join(collect_production_problems(settings, rate_limiter_mode="redis"))
    assert "wildcard" in joined.lower() or "'*'" in joined
    assert "TRUSTED_PROXY_CIDRS" in joined


def test_disabled_features_are_not_required(monkeypatch):
    _prod(monkeypatch,
          CORS_ALLOWED_ORIGINS="https://app.example.com", ALLOWED_HOSTS="app.example.com",
          RATE_LIMIT_BACKEND="redis", RATE_LIMIT_REDIS_URL="redis://r:6379/0", REDIS_ENABLED=True,
          DATABASE_ENABLED=False, AI_ENABLED=False, AI_PUBLIC_ENABLED=False,
          SUPABASE_URL="", SUPABASE_JWT_SECRET="", AUTH_TEST_HS256_SECRET="",
          RATE_LIMIT_TRUST_PROXY=False)
    assert collect_production_problems(settings, rate_limiter_mode="redis") == []


def test_enabled_features_missing_config_flagged(monkeypatch):
    _prod(monkeypatch,
          CORS_ALLOWED_ORIGINS="https://app.example.com", ALLOWED_HOSTS="app.example.com",
          RATE_LIMIT_BACKEND="redis", RATE_LIMIT_REDIS_URL="redis://r:6379/0", REDIS_ENABLED=True,
          DATABASE_ENABLED=True, DATABASE_URL="",
          AI_ENABLED=True, AI_PUBLIC_ENABLED=True, OPENROUTER_API_KEY="",
          AUTH_TEST_HS256_SECRET="leftover-test-secret-value-32-bytes+")
    joined = " ".join(collect_production_problems(settings, rate_limiter_mode="redis"))
    assert "DATABASE_URL" in joined
    assert "OPENROUTER_API_KEY" in joined
    assert "AUTH_TEST_HS256_SECRET" in joined


def test_enforce_raises_with_all_problems(monkeypatch):
    _prod(monkeypatch, CORS_ALLOWED_ORIGINS="", ALLOWED_HOSTS="")
    with pytest.raises(ProductionConfigError) as ei:
        enforce_production_config(settings, rate_limiter_mode="redis")
    assert len(ei.value.problems) >= 2


def test_hsts_is_not_required(monkeypatch):
    _prod(monkeypatch,
          CORS_ALLOWED_ORIGINS="https://app.example.com", ALLOWED_HOSTS="app.example.com",
          RATE_LIMIT_BACKEND="redis", RATE_LIMIT_REDIS_URL="redis://r:6379/0", REDIS_ENABLED=True,
          SECURITY_HSTS_ENABLED=False, DATABASE_ENABLED=False, AI_ENABLED=False, AI_PUBLIC_ENABLED=False,
          RATE_LIMIT_TRUST_PROXY=False, SUPABASE_URL="", SUPABASE_JWT_SECRET="", AUTH_TEST_HS256_SECRET="")
    assert collect_production_problems(settings, rate_limiter_mode="redis") == []
