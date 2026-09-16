"""Resolve the server-owned VN30, CW and underlying realtime universe.

Vnstock current groups are the live membership source. The bundled curated file remains
an explicit degraded startup fallback; verified contract terms stay in the registry and
are never inferred from listing membership.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.instruments.instrument_registry import InstrumentRegistry, instrument_registry
from app.instruments.instrument_schemas import (
    DataQualityStatus,
    InstrumentLifecycleStatus,
    MetadataVerificationStatus,
)


DEFAULT_UNIVERSE_FILE = Path(__file__).parent / "data" / "default_research_universe.json"
EXPECTED_STOCKS = 3
EXPECTED_COVERED_WARRANTS = 27
EXPECTED_UNIVERSE_SIZE = EXPECTED_STOCKS + EXPECTED_COVERED_WARRANTS
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9]{1,11}$")


@dataclass(frozen=True)
class UniverseIssue:
    symbol: str
    reason: str

    def to_wire(self) -> dict[str, str]:
        return {"symbol": self.symbol, "reason": self.reason}


@dataclass(frozen=True)
class ResolvedResearchUniverse:
    known_through: str | None
    items: tuple[dict[str, Any], ...]
    issues: tuple[UniverseIssue, ...]
    configured_size: int = 0
    expected_size: int = EXPECTED_UNIVERSE_SIZE
    expected_stocks: int = EXPECTED_STOCKS
    expected_covered_warrants: int = EXPECTED_COVERED_WARRANTS
    source: str = "STATIC_CURATED_FALLBACK"
    refreshed_at: str | None = None
    vn30_count: int = 0
    cw_underlying_count: int = 0
    extra_underlying_count: int = 0

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(str(item["symbol"]) for item in self.items)

    @property
    def stock_count(self) -> int:
        return sum(item.get("instrument_type") == "STOCK" for item in self.items)

    @property
    def covered_warrant_count(self) -> int:
        return sum(item.get("instrument_type") == "CW" for item in self.items)

    @property
    def complete(self) -> bool:
        return (
            not self.issues
            and self.configured_size == self.expected_size
            and len(self.items) == self.expected_size
            and self.stock_count == self.expected_stocks
            and self.covered_warrant_count == self.expected_covered_warrants
            and (self.source == "STATIC_CURATED_FALLBACK" or self.vn30_count == 30)
        )

    def health(self) -> dict[str, Any]:
        return {
            "status": "OK" if self.complete else "DEGRADED",
            "ownership": "server",
            "expected_size": self.expected_size,
            "configured_size": self.configured_size,
            "eligible_size": len(self.items),
            "expected_stocks": self.expected_stocks,
            "stock_count": self.stock_count,
            "expected_covered_warrants": self.expected_covered_warrants,
            "covered_warrant_count": self.covered_warrant_count,
            "source": self.source,
            "refreshed_at": self.refreshed_at,
            "vn30_count": self.vn30_count,
            "cw_underlying_count": self.cw_underlying_count,
            "extra_underlying_count": self.extra_underlying_count,
            "complete": self.complete,
            "issues": [issue.to_wire() for issue in self.issues],
        }


def _load_payload(path: Path) -> tuple[str | None, list[dict[str, Any]], list[UniverseIssue]]:
    try:
        raw = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001 - invalid deploy data must degrade, not abort startup
        return None, [], [UniverseIssue("__UNIVERSE__", f"load_failed:{exc.__class__.__name__}")]

    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        return None, [], [UniverseIssue("__UNIVERSE__", "invalid_document_shape")]

    items = [item for item in raw["items"] if isinstance(item, dict)]
    issues: list[UniverseIssue] = []
    if len(items) != len(raw["items"]):
        issues.append(UniverseIssue("__UNIVERSE__", "non_object_item"))
    if len(raw["items"]) != EXPECTED_UNIVERSE_SIZE:
        issues.append(
            UniverseIssue(
                "__UNIVERSE__",
                f"expected_{EXPECTED_UNIVERSE_SIZE}_items_found_{len(raw['items'])}",
            )
        )
    return raw.get("known_through"), items, issues


def _clean_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _duplicate_symbols(items: Iterable[dict[str, Any]]) -> set[str]:
    seen: set[str] = set()
    duplicated: set[str] = set()
    for item in items:
        symbol = _clean_symbol(item.get("symbol"))
        if symbol in seen:
            duplicated.add(symbol)
        seen.add(symbol)
    return duplicated


async def _resolve_static_research_universe(
    registry: InstrumentRegistry = instrument_registry,
    *,
    path: Path = DEFAULT_UNIVERSE_FILE,
    today: str | None = None,
) -> ResolvedResearchUniverse:
    """Load the canonical 3-stock/27-CW list and withhold unsafe CW entries.

    This function never raises for bad deploy data or registry availability.  A partial
    result is deliberately usable so the service can start in a truthful degraded mode.
    """

    known_through, configured_items, issues = _load_payload(path)
    if today is None:
        # Keep this lookup dynamic so tests and operational date overrides affect the
        # route and startup through the same seam.
        from app.instruments.providers import canonical_provider

        today = canonical_provider.get_vietnam_today()

    try:
        if not registry._is_initialized:
            await registry.initialize()
    except Exception as exc:  # noqa: BLE001 - report degraded universe, keep app alive
        issues.append(UniverseIssue("__REGISTRY__", f"initialization_failed:{exc.__class__.__name__}"))
        return ResolvedResearchUniverse(
            known_through, (), tuple(issues), configured_size=len(configured_items)
        )

    duplicates = _duplicate_symbols(configured_items)
    raw_stock_symbols = {
        _clean_symbol(item.get("symbol"))
        for item in configured_items
        if str(item.get("instrument_type", "")).strip().upper() == "STOCK"
    }
    if len(raw_stock_symbols) != EXPECTED_STOCKS:
        issues.append(
            UniverseIssue(
                "__UNIVERSE__",
                f"expected_{EXPECTED_STOCKS}_stocks_found_{len(raw_stock_symbols)}",
            )
        )

    resolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_item in configured_items:
        symbol = _clean_symbol(raw_item.get("symbol"))
        instrument_type = str(raw_item.get("instrument_type", "")).strip().upper()

        if not symbol or not _SYMBOL_RE.fullmatch(symbol):
            issues.append(UniverseIssue(symbol or "__MISSING_SYMBOL__", "invalid_symbol"))
            continue
        if symbol in seen:
            issues.append(UniverseIssue(symbol, "duplicate_symbol"))
            continue
        seen.add(symbol)
        if symbol in duplicates:
            # Retain the first canonical entry, but completeness stays degraded.
            pass
        if symbol == "VNINDEX":
            issues.append(UniverseIssue(symbol, "index_not_allowed_in_realtime_universe"))
            continue
        if instrument_type == "STOCK":
            resolved.append(
                {
                    "symbol": symbol,
                    "instrument_type": "STOCK",
                    "underlying_symbol": raw_item.get("underlying_symbol"),
                }
            )
            continue
        if instrument_type != "CW":
            issues.append(UniverseIssue(symbol, "invalid_instrument_type"))
            continue

        configured_underlying = _clean_symbol(raw_item.get("underlying_symbol"))
        spec = await registry.get_instrument(symbol)
        failures: list[str] = []
        if spec is None:
            failures.append("missing_registry_metadata")
        else:
            if spec.status != InstrumentLifecycleStatus.ACTIVE:
                failures.append(f"lifecycle_{spec.status.value.lower()}")
            if spec.metadata_verification != MetadataVerificationStatus.VERIFIED_CURRENT:
                failures.append(f"metadata_{spec.metadata_verification.value.lower()}")
            if spec.data_quality != DataQualityStatus.COMPLETE:
                failures.append("metadata_partial")
            if not spec.last_trading_date:
                failures.append("missing_last_trading_date")
            elif spec.last_trading_date < today:
                failures.append("last_trading_date_passed")
            if not spec.maturity_date:
                failures.append("missing_maturity_date")
            if not spec.issuer:
                failures.append("missing_issuer")
            if not spec.effective_strike or spec.effective_strike <= 0:
                failures.append("missing_strike")
            if not spec.effective_ratio or spec.effective_ratio <= 0:
                failures.append("missing_ratio")
            if not configured_underlying or configured_underlying not in raw_stock_symbols:
                failures.append("underlying_not_in_stock_universe")
            elif spec.underlying_symbol != configured_underlying:
                failures.append("underlying_conflict")

        if failures:
            issues.append(UniverseIssue(symbol, ",".join(failures)))
            continue

        # Các nhánh thiếu metadata đã bị loại ở trên; assertion giữ type-checker và
        # runtime contract đồng nhất trước khi dựng item đã xác thực.
        assert spec is not None

        resolved.append(
            {
                "symbol": symbol,
                "instrument_type": "CW",
                "underlying_symbol": spec.underlying_symbol,
                "issuer": spec.issuer,
                "strike_price": spec.effective_strike,
                "exercise_ratio": spec.effective_ratio,
                "maturity_date": spec.maturity_date,
                "last_trading_date": spec.last_trading_date,
                "metadata_verification": spec.metadata_verification.value,
                "data_quality": spec.data_quality.value,
            }
        )

    cw_count = sum(item.get("instrument_type") == "CW" for item in resolved)
    if cw_count != EXPECTED_COVERED_WARRANTS:
        issues.append(
            UniverseIssue(
                "__UNIVERSE__",
                f"expected_{EXPECTED_COVERED_WARRANTS}_covered_warrants_found_{cw_count}",
            )
        )

    return ResolvedResearchUniverse(
        known_through,
        tuple(resolved),
        tuple(issues),
        configured_size=len(configured_items),
    )


def _clean_symbols(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    return sorted({_clean_symbol(value) for value in values if _clean_symbol(value)})


async def _resolve_provider_research_universe(
    registry: InstrumentRegistry,
    provider: Any,
    *,
    force_refresh: bool,
) -> ResolvedResearchUniverse:
    snapshot = await provider.get_realtime_universe_snapshot(force_refresh=force_refresh)
    vn30 = _clean_symbols(snapshot.get("vn30_symbols"))
    cw_candidates = _clean_symbols(snapshot.get("covered_warrant_symbols"))
    issues: list[UniverseIssue] = []

    if len(vn30) != 30:
        issues.append(UniverseIssue("__VN30__", f"expected_30_members_found_{len(vn30)}"))

    valid_cws: list[str] = []
    underlying_by_cw: dict[str, str] = {}
    for symbol in cw_candidates:
        match = re.fullmatch(r"C([A-Z]{3})\d{4}", symbol)
        if match is None:
            issues.append(UniverseIssue(symbol, "invalid_covered_warrant_symbol"))
            continue
        valid_cws.append(symbol)
        underlying_by_cw[symbol] = match.group(1)

    if not valid_cws:
        issues.append(UniverseIssue("__CW__", "empty_current_provider_list"))

    observed_at = str(snapshot.get("as_of") or "") or None
    if not registry._is_initialized:
        await registry.initialize()

    cw_underlyings = sorted(set(underlying_by_cw.values()))
    extra_underlyings = sorted(set(cw_underlyings) - set(vn30))
    stock_symbols = sorted(set(vn30) | set(cw_underlyings))
    by_underlying: dict[str, list[str]] = {symbol: [] for symbol in stock_symbols}
    for symbol in valid_cws:
        by_underlying.setdefault(underlying_by_cw[symbol], []).append(symbol)

    items: list[dict[str, Any]] = []
    for stock in stock_symbols:
        items.append({
            "symbol": stock,
            "instrument_type": "STOCK",
            "underlying_symbol": None,
            "vn30_member": stock in set(vn30),
        })
        for symbol in sorted(by_underlying.get(stock, [])):
            spec = await registry.get_instrument(symbol)
            item: dict[str, Any] = {
                "symbol": symbol,
                "instrument_type": "CW",
                "underlying_symbol": stock,
            }
            if spec is not None:
                item.update({
                    "issuer": spec.issuer or None,
                    "strike_price": spec.effective_strike,
                    "exercise_ratio": spec.effective_ratio,
                    "maturity_date": spec.maturity_date,
                    "last_trading_date": spec.last_trading_date,
                    "metadata_verification": spec.metadata_verification.value,
                    "data_quality": spec.data_quality.value,
                })
            items.append(item)

    expected_stocks = len(stock_symbols)
    expected_cws = len(valid_cws)
    expected_size = expected_stocks + expected_cws
    known_through = str(snapshot.get("session_date") or "") or (
        observed_at[:10] if observed_at else None
    )
    return ResolvedResearchUniverse(
        known_through=known_through,
        items=tuple(items),
        issues=tuple(issues),
        configured_size=expected_size,
        expected_size=expected_size,
        expected_stocks=expected_stocks,
        expected_covered_warrants=expected_cws,
        source=str(snapshot.get("source") or "VNSTOCK_CURRENT_GROUPS"),
        refreshed_at=observed_at,
        vn30_count=len(vn30),
        cw_underlying_count=len(cw_underlyings),
        extra_underlying_count=len(extra_underlyings),
    )


_latest_resolved_universe: ResolvedResearchUniverse | None = None


def latest_resolved_research_universe() -> ResolvedResearchUniverse | None:
    return _latest_resolved_universe


def publish_resolved_research_universe(universe: ResolvedResearchUniverse) -> None:
    """Công bố universe chỉ sau khi live owner đã chấp nhận candidate."""
    global _latest_resolved_universe
    _latest_resolved_universe = universe


async def reconcile_registry_with_research_universe(
    registry: InstrumentRegistry,
    universe: ResolvedResearchUniverse,
) -> int:
    """Commit lifecycle membership only after the live owner accepts the universe."""
    if not universe.complete or universe.source == "STATIC_CURATED_FALLBACK":
        return 0
    symbols = [
        str(item["symbol"])
        for item in universe.items
        if item.get("instrument_type") == "CW"
    ]
    return await registry.reconcile_current_market_warrants(
        symbols,
        source=universe.source,
        observed_at=universe.refreshed_at,
    )


async def resolve_default_research_universe(
    registry: InstrumentRegistry = instrument_registry,
    *,
    provider: Any | None = None,
    force_refresh: bool = False,
    path: Path = DEFAULT_UNIVERSE_FILE,
    today: str | None = None,
) -> ResolvedResearchUniverse:
    """Resolve universe VN30 + CW live, dùng file curated làm fallback."""
    if provider is not None:
        try:
            resolved = await _resolve_provider_research_universe(
                registry, provider, force_refresh=force_refresh
            )
            return resolved
        except Exception as exc:  # noqa: BLE001 - a listing outage cannot block startup
            fallback = await _resolve_static_research_universe(
                registry, path=path, today=today
            )
            issues = (
                UniverseIssue("__DYNAMIC_UNIVERSE__", f"refresh_failed:{exc.__class__.__name__}"),
                *fallback.issues,
            )
            fallback = ResolvedResearchUniverse(
                known_through=fallback.known_through,
                items=fallback.items,
                issues=issues,
                configured_size=fallback.configured_size,
                expected_size=fallback.expected_size,
                expected_stocks=fallback.expected_stocks,
                expected_covered_warrants=fallback.expected_covered_warrants,
                source="STATIC_CURATED_FALLBACK",
            )
            return fallback

    resolved = await _resolve_static_research_universe(registry, path=path, today=today)
    return resolved
