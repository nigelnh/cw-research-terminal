"""Map provider ``HistoricalBar`` objects to persistence ``BarUpsert`` rows.

Applies the completed-bar policy: a still-forming bar is dropped by default so canonical
historical research data never contains a provisional value that later silently becomes
"final".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from app.market_data.market_schemas import HistoricalBar
from app.persistence.ingestion.trading_calendar import (
    TIMEFRAME_MINUTES,
    intraday_bar_is_complete,
    last_completed_session_date,
)
from app.persistence.market_time import normalize_timeframe, parse_vendor_timestamp
from app.persistence.rows import BarUpsert

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MappedBars:
    rows: list[BarUpsert]
    dropped_incomplete: int
    dropped_unparseable: int
    max_ts: datetime | None
    min_ts: datetime | None


def map_history(
    bars: list[HistoricalBar],
    *,
    instrument_id: int,
    timeframe: str,
    price_basis: str,
    source: str,
    include_forming: bool = False,
    now_vn: datetime | None = None,
) -> MappedBars:
    tf = normalize_timeframe(timeframe)
    tf_minutes = TIMEFRAME_MINUTES[tf]
    cutoff_session = last_completed_session_date(now_vn)

    rows: list[BarUpsert] = []
    dropped_incomplete = 0
    dropped_unparseable = 0
    max_ts: datetime | None = None
    min_ts: datetime | None = None

    for b in bars:
        try:
            ts_utc, session_date = parse_vendor_timestamp(b.date, timeframe=tf)
        except (ValueError, TypeError):
            dropped_unparseable += 1
            continue

        if not include_forming:
            if tf == "1d":
                if session_date > cutoff_session:
                    dropped_incomplete += 1
                    continue
            else:
                if not intraday_bar_is_complete(ts_utc, tf_minutes, now_vn):
                    dropped_incomplete += 1
                    continue

        rows.append(
            BarUpsert(
                instrument_id=instrument_id,
                timeframe=tf,
                ts=ts_utc,
                open=float(b.open),
                high=float(b.high),
                low=float(b.low),
                close=float(b.close),
                volume=int(b.volume),
                price_basis=price_basis,
                source=source,
                session_date=session_date,
            )
        )
        max_ts = ts_utc if max_ts is None or ts_utc > max_ts else max_ts
        min_ts = ts_utc if min_ts is None or ts_utc < min_ts else min_ts

    if dropped_unparseable:
        logger.warning("map_history: %d unparseable bar timestamps skipped", dropped_unparseable)
    return MappedBars(
        rows=rows,
        dropped_incomplete=dropped_incomplete,
        dropped_unparseable=dropped_unparseable,
        max_ts=max_ts,
        min_ts=min_ts,
    )
