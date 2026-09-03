"""Canonical loader and runtime validation for the default realtime universe.

The JSON file is the product-owned list.  Runtime registry data is the source of
truth for whether each covered warrant is still safe to stream and model.  Invalid
entries are withheld rather than replaced, and the resulting completeness report is
kept for health/status responses.
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


async def resolve_default_research_universe(
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
