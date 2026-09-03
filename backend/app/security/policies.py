"""The one place endpoint rate-limit policy lives - no scattered magic numbers.

Each policy: a compiled path pattern + methods -> a tier name, the ``limits`` items
(read from settings), the key scope, and whether the tier is cost-fail-closed.

Resolution is first-match-wins over an ordered list, so specific patterns precede
generic ones. Anything unmatched under ``/api`` falls to the ``default`` tier; anything
outside ``/api`` (docs, openapi.json) is unlimited.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.core.config import settings
from app.security.rate_limiter import RateLimitItem, per_hour, per_minute


@dataclass(frozen=True, slots=True)
class RoutePolicy:
    tier: str
    pattern: re.Pattern[str]
    methods: frozenset[str]  # {"*"} matches all
    key_scope: str  # "ip" | "subject_or_ip"
    fail_closed: bool = False
    _items_factory: object = field(default=None, repr=False)

    def matches(self, method: str, path: str) -> bool:
        if "*" not in self.methods and method.upper() not in self.methods:
            return False
        return self.pattern.match(path) is not None

    def items(self) -> tuple[RateLimitItem, ...]:
        return self._items_factory()  # type: ignore[operator]


def _p(regex: str) -> re.Pattern[str]:
    return re.compile(regex)


@lru_cache(maxsize=1)
def policy_table() -> tuple[RoutePolicy, ...]:
    """Ordered, first-match-wins. Cached; call ``policy_table.cache_clear()`` after
    mutating the relevant settings (tests do)."""
    return (
        # ---- Tier E: AI - very strict, fail-closed (spends real money) ----
        RoutePolicy(
            tier="ai",
            pattern=_p(r"^/api/ai/(?:chat|files/extract)/?$"),
            methods=frozenset({"POST"}),
            key_scope="ip",
            fail_closed=True,
            _items_factory=lambda: (per_minute(settings.RL_AI_PER_MIN), per_hour(settings.RL_AI_PER_HOUR)),
        ),
        RoutePolicy(
            tier="ai_health",
            pattern=_p(r"^/api/ai/health/?$"),
            methods=frozenset({"*"}),
            key_scope="ip",
            _items_factory=lambda: (per_minute(settings.RL_HEALTH_PER_MIN),),
        ),
        # ---- Tier D: history - DB + possible provider gap-fill ----
        RoutePolicy(
            tier="history",
            pattern=_p(r"^/api/market/history/"),
            methods=frozenset({"*"}),
            key_scope="ip",
            _items_factory=lambda: (per_minute(settings.RL_HISTORY_PER_MIN),),
        ),
        # ---- Tier A: health / tiny metadata ----
        RoutePolicy(
            tier="health",
            pattern=_p(r"^(/health|/api/market/health|/api/instruments/metrics/)"),
            methods=frozenset({"*"}),
            key_scope="ip",
            _items_factory=lambda: (per_minute(settings.RL_HEALTH_PER_MIN),),
        ),
        # ---- Tier C: quant ----
        RoutePolicy(
            tier="quant",
            pattern=_p(r"^/api/quant/"),
            methods=frozenset({"*"}),
            key_scope="ip",
            _items_factory=lambda: (per_minute(settings.RL_QUANT_PER_MIN),),
        ),
        # ---- Tier F: authenticated writes/reads - keyed by verified sub ----
        RoutePolicy(
            tier="me",
            pattern=_p(r"^/api/me/"),
            methods=frozenset({"*"}),
            key_scope="subject_or_ip",
            _items_factory=lambda: (per_minute(settings.RL_ME_PER_MIN),),
        ),
        # ---- Tier B: ordinary market-data + instrument reads ----
        RoutePolicy(
            tier="market",
            pattern=_p(r"^/api/(market|instruments)/"),
            methods=frozenset({"*"}),
            key_scope="ip",
            _items_factory=lambda: (per_minute(settings.RL_MARKET_PER_MIN),),
        ),
        RoutePolicy(
            tier="market",
            pattern=_p(r"^/api/instruments/?$"),
            methods=frozenset({"*"}),
            key_scope="ip",
            _items_factory=lambda: (per_minute(settings.RL_MARKET_PER_MIN),),
        ),
        # ---- catch-all for any other /api route ----
        RoutePolicy(
            tier="default",
            pattern=_p(r"^/api/"),
            methods=frozenset({"*"}),
            key_scope="ip",
            _items_factory=lambda: (per_minute(settings.RL_DEFAULT_PER_MIN),),
        ),
    )


def resolve_policy(method: str, path: str) -> RoutePolicy | None:
    for policy in policy_table():
        if policy.matches(method, path):
            return policy
    return None
