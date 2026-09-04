"""Canonical temporal data-state model (Step 13C).

Every value the terminal displays carries exactly one temporal origin. The UI must be able
to answer, for any cell: what is the value, which trading session is it from, when was it
observed, is it live, is it last-session, is it unavailable and why. This module is the
vocabulary; the resolver (`market_snapshot_resolver`) assigns it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DataTemporalState(str, Enum):
    LIVE = "LIVE"                  # fresh tick during an active session
    SESSION_SNAPSHOT = "SESSION_SNAPSHOT"  # current-session value while matching is paused
    LAST_SESSION = "LAST_SESSION"  # final / most-recent value from the last completed session
    HISTORICAL = "HISTORICAL"      # persisted daily bar older than the last completed session
    DERIVED = "DERIVED"            # computed from other stated values (e.g. change vs prior close)
    UNAVAILABLE = "UNAVAILABLE"    # realtime-only field with no legitimate fallback


class DataSource(str, Enum):
    LIVE_FEED = "LIVE_FEED"                  # FiinQuant SignalR -> MarketState
    REDIS_WARM = "REDIS_WARM"                # warm-cache restore (still same-session)
    SNAPSHOT_FINAL = "SNAPSHOT_FINAL"        # instrument_snapshots, quality=FINAL (session close)
    SNAPSHOT_CHECKPOINT = "SNAPSHOT_CHECKPOINT"  # instrument_snapshots, mid-session checkpoint
    SNAPSHOT_SEED = "SNAPSHOT_SEED"          # instrument_snapshots seeded from EOD bars (no book)
    EOD_BARS = "EOD_BARS"                    # market_bars daily close/OHLC/volume
    PRIOR_CLOSE = "PRIOR_CLOSE"              # previous trading session's close (used as reference)
    SESSION_REFERENCE = "SESSION_REFERENCE"  # provider snapshot: prior close + session bands
    QUANT_LIVE = "QUANT_LIVE"               # LiveQuantEngine, current session
    QUANT_EOD = "QUANT_EOD"                 # LiveQuantEngine recomputed for a completed session
    NONE = "NONE"                            # no source


# Row-level badge the UI can render without inspecting every field group.
class DisplayState(str, Enum):
    LIVE = "LIVE"
    LAST_SESSION = "LAST_SESSION"
    MIXED = "MIXED"              # some groups live, some last-session (e.g. transition minute)
    UNAVAILABLE = "UNAVAILABLE"  # nothing legitimate to show
    SESSION_SNAPSHOT = "SESSION_SNAPSHOT"


@dataclass(frozen=True)
class FieldProvenance:
    """Temporal origin of one *group* of related fields (quote / book / analytics)."""

    state: DataTemporalState
    source: DataSource
    as_of: str | None = None        # ISO8601 (VN) instant the value was observed/computed
    session_date: str | None = None  # VN trading-session date the value belongs to
    stale: bool = False              # true when the value is older than the last completed session
    note: str | None = None          # short human reason, esp. for UNAVAILABLE

    def to_wire(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "state": self.state.value,
            "source": self.source.value,
        }
        if self.as_of is not None:
            d["asOf"] = self.as_of
        if self.session_date is not None:
            d["sessionDate"] = self.session_date
        if self.stale:
            d["stale"] = True
        if self.note:
            d["note"] = self.note
        return d


UNAVAILABLE_QUOTE = FieldProvenance(DataTemporalState.UNAVAILABLE, DataSource.NONE)


def derive_display_state(groups: list[FieldProvenance]) -> DisplayState:
    states = {g.state for g in groups if g.state != DataTemporalState.UNAVAILABLE}
    if not states:
        return DisplayState.UNAVAILABLE
    if states == {DataTemporalState.LIVE}:
        return DisplayState.LIVE
    if states == {DataTemporalState.SESSION_SNAPSHOT}:
        return DisplayState.SESSION_SNAPSHOT
    if DataTemporalState.LIVE in states:
        return DisplayState.MIXED
    return DisplayState.LAST_SESSION
