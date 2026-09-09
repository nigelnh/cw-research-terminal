"""SSI iBoard realtime wire helpers.

The public ``vnstock-js`` project documents the unauthenticated SSI iBoard
subscription envelope and the positions in its pipe-delimited quote message.  Keep the
wire parser at the provider boundary: the rest of the application only sees canonical
raw-VND events.

Protocol reference: https://github.com/ttqteo/vnstock-js/tree/master/src/realtime
License: Apache-2.0 (see THIRD_PARTY_NOTICES.md)
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

SSI_REALTIME_URL = "wss://iboard-pushstream.ssi.com.vn/realtime"
SSI_REALTIME_TOPIC = "stockRealtimeBySymbolsAndBoards"
# SSI currently rejects aiohttp's default Python User-Agent at the HTTP upgrade with 403.
# An explicit, honest product UA succeeds; no cookie, token, Origin, or browser emulation is
# required. Keep this at the transport edge so it is observable and regression-tested.
SSI_REALTIME_USER_AGENT = (
    "Mozilla/5.0 (compatible; CWTerminal/1.0; "
    "+https://github.com/nigelnh/cw-research-terminal)"
)
_SYMBOL = re.compile(r"^[A-Z0-9]{2,16}$")


class SsiRealtimeParseError(ValueError):
    """A frame is not a supported SSI equity price-table observation."""


def _number(parts: list[str], index: int) -> float | None:
    if index >= len(parts) or not parts[index].strip():
        return None
    try:
        value = float(parts[index])
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _quantity(parts: list[str], index: int) -> int | None:
    value = _number(parts, index)
    return None if value is None else max(0, int(value))


def _price(parts: list[str], index: int) -> float | None:
    """SSI sends prices in raw VND. Zero is an explicitly empty book/trade value."""
    value = _number(parts, index)
    return value if value is not None and value > 0 else None


def subscription_message(symbols: list[str], *, subscribe: bool = True) -> str:
    clean = sorted(
        {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
    )
    return json.dumps(
        {
            "type": "sub" if subscribe else "unsub",
            "topic": SSI_REALTIME_TOPIC,
            "variables": {"symbols": clean, "boardIds": ["MAIN"]},
            "component": "priceTableEquities",
        },
        separators=(",", ":"),
    )


def parse_realtime_frame(raw: str) -> dict[str, Any]:
    """Parse one SSI price-table frame without inventing timestamps or sessions.

    ``vnstock-js`` converts prices to thousands of VND for its public JavaScript API.
    The terminal contract uses raw VND, so this parser intentionally keeps wire units.
    Receipt time and the canonical session are assigned by the owning provider.
    """
    if not isinstance(raw, str) or "|" not in raw:
        raise SsiRealtimeParseError("not a pipe-delimited realtime frame")
    parts = raw.split("|")
    if len(parts) <= 66:
        raise SsiRealtimeParseError(
            "realtime frame is shorter than the supported schema"
        )
    symbol_field = parts[1].split("#", 1)
    symbol = (symbol_field[1] if len(symbol_field) == 2 else "").strip().upper()
    if not _SYMBOL.fullmatch(symbol):
        raise SsiRealtimeParseError("realtime frame has no valid symbol")

    return {
        "exchange": parts[0].strip().upper() or None,
        "symbol": symbol,
        "bids": [
            {"price": _price(parts, 2), "volume": _quantity(parts, 3)},
            {"price": _price(parts, 4), "volume": _quantity(parts, 5)},
            {"price": _price(parts, 6), "volume": _quantity(parts, 7)},
        ],
        "asks": [
            {"price": _price(parts, 22), "volume": _quantity(parts, 23)},
            {"price": _price(parts, 24), "volume": _quantity(parts, 25)},
            {"price": _price(parts, 26), "volume": _quantity(parts, 27)},
        ],
        "matched_price": _price(parts, 42),
        "matched_volume": _quantity(parts, 43),
        "change": _number(parts, 52),
        "change_percent": _number(parts, 53),
        "total_buy_volume": _quantity(parts, 48),
        "total_buy_value": _number(parts, 49),
        "total_volume": _quantity(parts, 54),
        "total_value": _number(parts, 55),
        "provider_updated": _quantity(parts, 65),
        "side": "buy" if parts[66].strip().lower() == "b" else "sell",
    }
