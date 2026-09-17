"""Current covered-warrant contract terms from VNDirect's public finfo API.

The Vnstock ``CW`` group is used as listing membership.  This source supplies the
contract fields that membership cannot prove: current exercise price/ratio, issuer and
trading dates.  Keeping the two concerns separate prevents a symbol-only discovery from
silently becoming quant-ready.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.instruments.instrument_schemas import (
    DataQualityStatus,
    InstrumentLifecycleStatus,
    LifecycleEvidenceLevel,
    MetadataVerificationStatus,
)
from app.market_data.trading_calendar import VN_TZ


_ISSUER_ALIASES = {
    "ACB": "ACBS",
    "HSC": "HCM",
    "KIS": "KISVN",
    "TCX": "TCBS",
    "VNDS": "VND",
}

_BUNDLED_TERMS_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "current_warrant_terms.json"
)


def load_bundled_current_warrant_terms(
    session_date: str,
    *,
    path: Path = _BUNDLED_TERMS_FILE,
) -> dict[str, dict[str, Any]]:
    """Read the last successful terms snapshot, retaining only still-tradable rows."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rows = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return {}
    retrieved_at = str(payload.get("retrieved_at") or "")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized = normalize_current_warrant_term(
            row,
            retrieved_at=retrieved_at,
            base_url="https://api-finfo.vndirect.com.vn/v4",
        )
        if normalized and normalized["last_trading_date"] >= session_date:
            result[normalized["symbol"]] = normalized
    return result


def _positive_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _ratio(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.split(":", 1)[0].strip()
    return _positive_number(value)


def _date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def normalize_current_warrant_term(
    raw: dict[str, Any], *, retrieved_at: str, base_url: str
) -> dict[str, Any] | None:
    symbol = str(raw.get("code") or "").strip().upper()
    underlying = str(raw.get("underlyingAsset") or "").strip().upper()
    strike = _positive_number(raw.get("exercisePrice"))
    ratio = _ratio(raw.get("exerciseRatio"))
    maturity = _date(raw.get("expiryDate"))
    last_trading = _date(raw.get("lastTradingDate"))
    if not symbol or not underlying or not strike or not ratio or not maturity or not last_trading:
        return None

    issuer_raw = str(raw.get("issuer") or raw.get("issuerName") or "").strip().upper()
    issuer = _ISSUER_ALIASES.get(issuer_raw, issuer_raw)
    if not issuer:
        return None

    source_url = (
        f"{base_url.rstrip('/')}/derivatives?"
        f"q={quote(f'code:{symbol}~locale:VN', safe=':~')}&size=1"
    )
    listed_volume = _positive_number(raw.get("listedQtty"))
    return {
        "symbol": symbol,
        "issuer": issuer,
        "underlying_symbol": underlying,
        "strike_price": strike,
        "exercise_ratio": ratio,
        "effective_strike_price": strike,
        "effective_exercise_ratio": ratio,
        "maturity_date": maturity,
        "last_trading_date": last_trading,
        "listed_volume": int(listed_volume) if listed_volume is not None else None,
        "instrument_type": "CW",
        "status": InstrumentLifecycleStatus.ACTIVE,
        "data_quality": DataQualityStatus.COMPLETE,
        "evidence_level": LifecycleEvidenceLevel.CURRENT_BROKER_MARKET_LIST,
        "metadata_verification": MetadataVerificationStatus.VERIFIED_CURRENT,
        "metadata_source": "VNDIRECT_FINFO_CURRENT_DERIVATIVES",
        "metadata_retrieved_at": retrieved_at,
        "provenance": {
            "effective_terms_source": {
                "source_type": "CURRENT_BROKER_TERMS",
                "source_url": source_url,
                "retrieved_at": retrieved_at,
                "notes": "Current effective CW terms from VNDirect finfo; lifecycle cross-checked against the Vnstock current CW group.",
            },
            "reconciliation_mode": "AUTOMATIC_SCRAPED",
        },
    }


async def fetch_current_warrant_terms(
    session_date: str,
    *,
    base_url: str,
    timeout_seconds: float = 12.0,
    client: httpx.AsyncClient | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch every CW whose first/last trading dates contain ``session_date``.

    The endpoint currently fits in one 500-row page. Pagination remains explicit so a
    larger future universe cannot be silently truncated.
    """

    session = date.fromisoformat(session_date).isoformat()
    query = (
        f"derType:CW~lastTradingDate:gte:{session}~"
        f"firstTradingDate:lte:{session}~locale:VN"
    )
    owns_client = client is None
    http = client or httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds),
        headers={
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://dchart.vndirect.com.vn",
            "Referer": "https://dchart.vndirect.com.vn/",
            "User-Agent": "CW-Research-Terminal/1.0 (+public-market-metadata)",
        },
    )
    retrieved_at = datetime.now(VN_TZ).isoformat()
    result: dict[str, dict[str, Any]] = {}
    page = 1
    try:
        while True:
            response = await http.get(
                f"{base_url.rstrip('/')}/derivatives",
                params={"q": query, "size": 500, "page": page},
            )
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise ValueError("VNDirect derivatives response has no data list")
            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                normalized = normalize_current_warrant_term(
                    raw, retrieved_at=retrieved_at, base_url=base_url
                )
                if normalized is not None:
                    result[normalized["symbol"]] = normalized

            total_pages = int(payload.get("totalPages") or 1)
            if page >= total_pages:
                break
            page += 1
            if page > 10:
                raise ValueError("VNDirect derivatives pagination exceeded safety limit")
    finally:
        if owns_client:
            await http.aclose()
    if not result:
        raise ValueError("VNDirect returned no current covered-warrant terms")
    return result
