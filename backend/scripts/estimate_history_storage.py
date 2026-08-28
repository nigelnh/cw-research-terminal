#!/usr/bin/env python3
"""Back-of-envelope PostgreSQL storage estimate for 2 years of historical market bars.

Assumptions are documented inline and in docs/persistence/STORAGE_SIZING.md. Run:

    python backend/scripts/estimate_history_storage.py
"""

from __future__ import annotations

# --- trading calendar -------------------------------------------------------
SESSIONS_PER_YEAR = 250          # HOSE ~ 250 trading days / year
YEARS = 2
SESSIONS = SESSIONS_PER_YEAR * YEARS   # 500

# Continuous-session minutes on HOSE (09:00-11:30 + 13:00-14:45, ATC excluded) ~ 255.
BARS_PER_SESSION = {
    "1d": 1,
    "1h": 5,      # 09,10,11,13,14 buckets
    "5m": 52,     # ceil(255/5)
    "1m": 250,    # ~ continuous trading minutes
}

# --- instrument universes --------------------------------------------------
# Set A: every CW that traded in the 2y window + their underlyings + indexes.
#   ~500 distinct CWs cycle through HOSE over 2 years, ~30 blue-chip underlyings, 2 indexes.
UNIVERSE_A = 500 + 30 + 2        # 532
# Set B: core underlying universe only (underlyings + indexes).
UNIVERSE_B = 30 + 2             # 32

# --- per-row cost in PostgreSQL ------------------------------------------------
# market_bars heap tuple: 23B header + ~padding + column payload
#   id 8, instrument_id 8, timeframe ~5, ts 8, session_date 4, price_basis ~7,
#   open/high/low/close NUMERIC ~9 each = 36, volume 8, source ~10,
#   ingestion_run_id 8, created_at 8, updated_at 8  => ~126B payload
# + 28B tuple header/pad + 4B item pointer => ~158B, +20% real-world slack => ~190B heap
HEAP_BYTES_PER_ROW = 190
# indexes: PK btree on id (~36B/row @ 2/3 fill) + composite UNIQUE
#   (instrument_id,timeframe,ts,price_basis) (~74B/row) => ~110B
INDEX_BYTES_PER_ROW = 110
BYTES_PER_ROW = HEAP_BYTES_PER_ROW + INDEX_BYTES_PER_ROW   # ~300


def rows_per_instrument(tf: str) -> int:
    return BARS_PER_SESSION[tf] * SESSIONS


def fmt(nbytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:,.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:,.1f} PB"


def main() -> None:
    print(f"Trading sessions in {YEARS}y: {SESSIONS}")
    print(f"Per-row cost: {HEAP_BYTES_PER_ROW}B heap + {INDEX_BYTES_PER_ROW}B index = {BYTES_PER_ROW}B\n")
    header = f"{'tf':>4} | {'rows/inst':>12} | {'Set A rows':>14} | {'Set A size':>12} | {'Set B rows':>12} | {'Set B size':>12}"
    print(header)
    print("-" * len(header))
    for tf in ("1d", "1h", "5m", "1m"):
        rpi = rows_per_instrument(tf)
        a_rows = rpi * UNIVERSE_A
        b_rows = rpi * UNIVERSE_B
        print(
            f"{tf:>4} | {rpi:>12,} | {a_rows:>14,} | {fmt(a_rows * BYTES_PER_ROW):>12} | "
            f"{b_rows:>12,} | {fmt(b_rows * BYTES_PER_ROW):>12}"
        )
    print(f"\nSet A instruments: {UNIVERSE_A}   Set B instruments: {UNIVERSE_B}")
    print("Free tier reference: Supabase 500 MB, Neon ~500 MB included.")


if __name__ == "__main__":
    main()
