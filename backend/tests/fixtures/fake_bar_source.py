"""
Test double for `HistoricalVolatilityService`'s upstream historical-bar source.

`FakeBarSource` satisfies the `HistoricalBarSource` protocol (one async method) and records
every call so tests can assert single-flight / no-repeat-fetch behavior. It performs NO
network or disk I/O.
"""

import asyncio
import math
from datetime import date, timedelta
from typing import Dict, List, Optional

from app.market_data.market_schemas import HistoricalBar


def synthetic_closes(n: int = 40, base: float = 22000.0) -> List[float]:
    """Deterministic price series with genuine variance (sample std > 0)."""
    return [
        round(base * (1.0 + 0.03 * math.sin(i * 0.6) + 0.0012 * i), 2)
        for i in range(n)
    ]


def make_daily_bars(closes: List[float], start: str | None = None) -> List[HistoricalBar]:
    """Build a list of daily `HistoricalBar` from a close series (adjusted)."""
    d = date.fromisoformat(start) if start else date.today() - timedelta(days=len(closes) - 1)
    bars: List[HistoricalBar] = []
    for c in closes:
        c = float(c)
        bars.append(
            HistoricalBar(
                date=d.isoformat(),
                open=c,
                high=round(c * 1.01, 2),
                low=round(c * 0.99, 2),
                close=c,
                volume=1_000_000,
                adjusted=True,
            )
        )
        d += timedelta(days=1)
    return bars


class FakeBarSource:
    """In-memory `HistoricalBarSource`. Records calls; never touches the network."""

    def __init__(
        self,
        bars_by_symbol: Optional[Dict[str, List[HistoricalBar]]] = None,
        *,
        fail: bool = False,
        fail_exc: Optional[BaseException] = None,
        call_delay: float = 0.0,
    ) -> None:
        self._bars: Dict[str, List[HistoricalBar]] = {
            k.upper(): v for k, v in (bars_by_symbol or {}).items()
        }
        self._fail = fail
        self._fail_exc = fail_exc or RuntimeError("simulated upstream failure")
        self._call_delay = call_delay
        self.calls: List[dict] = []
        self.call_count_by_symbol: Dict[str, int] = {}

    def set_bars(self, symbol: str, bars: List[HistoricalBar]) -> None:
        self._bars[symbol.upper()] = bars

    async def get_historical_bars(
        self,
        symbol: str,
        timeframe: str = "1D",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        adjusted: bool = True,
    ) -> List[HistoricalBar]:
        sym = symbol.upper()
        self.calls.append({"symbol": sym, "timeframe": timeframe, "adjusted": adjusted})
        self.call_count_by_symbol[sym] = self.call_count_by_symbol.get(sym, 0) + 1
        if self._call_delay:
            await asyncio.sleep(self._call_delay)
        if self._fail:
            raise self._fail_exc
        return list(self._bars.get(sym, []))
