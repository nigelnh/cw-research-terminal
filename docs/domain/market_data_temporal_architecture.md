# Market Data Temporal Architecture

How the terminal decides **what value to show, from which trading session, and how fresh it
is** — during a live HOSE session and, crucially, outside one.

## The problem this solves

HOSE trades ~09:00–15:00 ICT on trading weekdays. Outside that window a realtime feed has
nothing new to say, so the naive behaviour ("show live or show nothing") leaves the terminal
almost blank on evenings, weekends and the ~10 exchange holidays a year. That is honest but
useless for research. The fix is a layered fallback that surfaces the **last completed
session's** legitimate values, each explicitly labelled — never presented as live, never
fabricated.

## 1. Canonical trading calendar

One module — `app/market_data/trading_calendar.py` — owns every trading-day / session
decision. `market_session.py` and the ingestion gap-classifier are thin shims over it.

- **Session boundaries** (Asia/Ho_Chi_Minh, fixed UTC+7): morning 09:00–11:30, lunch
  11:30–13:00, afternoon 13:00–15:00.
- **Trading days** = weekdays minus HOSE exchange holidays. The holiday set is
  **hand-maintained** from the official HOSE *"Notice of trading holiday schedule"*
  (one per year). 2024 / 2025 / 2026 are confirmed (`AUTHORITATIVE`); 2027 is a best-effort
  provisional set (`APPROXIMATE`); beyond that, weekends + the four fixed-date public
  holidays + an approximate Tet window. `calendar_confidence()` reports which regime a date
  falls in.
- **Overrides**: `EXCHANGE_CALENDAR_OVERRIDES_JSON` env adds/removes closure dates without a
  code change (exceptional closures, a Tet-date correction).
- **Navigation**: `previous_trading_session(d)`, `latest_completed_trading_session(now)`
  (most recent date whose 15:00 close has passed), `next_trading_session_open(now)`,
  `trading_sessions_between(a, b)`. Nothing anywhere does `today - 1 day`.

## 2. Temporal data-state model

Every displayed value carries one origin (`app/market_data/temporal.py`):

| State | Meaning |
|---|---|
| `LIVE` | fresh tick during an active session |
| `LAST_SESSION` | final / latest value from the last completed session |
| `HISTORICAL` | a persisted daily bar older than the last completed session |
| `DERIVED` | computed from other stated values (e.g. change vs prior close) |
| `UNAVAILABLE` | realtime-only field with no legitimate fallback |

A dashboard row carries a `provenance` block — `{ quote, book, analytics }`, each with
`state / source / asOf / sessionDate / stale` — plus a row-level `displayState`
(`LIVE | LAST_SESSION | MIXED | UNAVAILABLE`).

## 3. Realtime path (unchanged)

FiinQuant SignalR (single owner) → normalized `MarketState` (L1, in-process) → Redis warm
cache (L2, 24 h TTL, staleness-gated) → FastAPI WebSocket `/ws/market` → the frontend WS
client, which is the **single live owner** of the quote/analytics maps. During an active
session this path is authoritative for every field it supplies.

## 4. After-hours fallback resolver

`app/market_data/market_snapshot_resolver.py`, exposed as
`GET /api/market/dashboard?symbols=…`. Per field group, in order:

| # | Source | Supplies |
|---|---|---|
| A | **LIVE** — active session + a fresh `MarketState` tick | everything the tick carries |
| B | **`instrument_snapshots`** — last completed session's persisted snapshot | ref, last, change, OHLC, volume, **and the closing bid/ask** (only from a real observed snapshot, not the EOD seed) |
| C | **`market_bars`** daily — EOD close/OHLC/volume for the symbol's latest session | last = close, OHLC, volume; reference = **previous session's close**; change = `DERIVED`. One controlled provider gap-fill for a missing latest-session bar, then persist + reuse. **No bid/ask** (FiinQuant serves no historical order book). |
| D | **UNAVAILABLE** | realtime-only fields with no B source → `null`, never fabricated |

"No trade this session" is distinct from "the bar is missing": the snapshot/bar
`session_date` is preserved verbatim, so a warrant that last traded two sessions ago shows
that real date with `state = HISTORICAL`, not a faked recent one.

`GET /api/market/_diag/{symbol}` returns the full decision trace (candidates, chosen source,
session, whether a gap-fill fired) — sanitized, no provider payloads.

## 5. Last-valid snapshot persistence

`instrument_snapshots` (Alembic `0003`) — one upserted row per `(symbol, session_date)`.
Written by `SnapshotCheckpointer`, a bounded lifespan-owned task:

- a throttled per-symbol checkpoint (default 90 s) during an active session, **only when the
  quote changed** — not on every tick;
- a `FINAL` checkpoint at the 15:00 close and once on graceful shutdown.

Guards in `SnapshotRepository.upsert`: never regress to an older session; within a session
`captured_at` only advances and `quality` never downgrades `FINAL → INTRADAY_CHECKPOINT`.
This is the **only** durable source of an after-hours closing bid/ask, and it makes a
Railway crash/redeploy before close non-destructive. Redis is warm state only; a Redis
eviction or restart cannot make last-session research disappear.

## 6. EOD quant — temporal alignment

`LiveQuantEngine.compute_eod_analytics(cw, session_date)` recomputes analytics for a
completed session with **both legs from that same session**: CW close (RAW) + underlying
close (ADJUSTED), with `T` / DTE / lifecycle evaluated at 15:00 ICT of `session_date`. It
never mixes a `T-1` CW price with a `T` underlying price — a missing leg yields
`EOD_INPUT_MISSING (<leg>@<date>)`. Produces IV-trade, Greeks, theoretical value, moneyness,
DTE. IV-bid / IV-ask / spread are `UNAVAILABLE` (no EOD order book). The metadata gate is
identical to live — `CONFLICTING` terms (e.g. CTCB2601) stay closed. Results are cached per
`(symbol, session_date)`.

Field-by-field source matrix, the FiinQuant capability findings, and the research-universe /
subscription-capacity model are in `STEP_13C_REPORT.md`.

## 7. Research universe & subscription capacity

- **Registry = the research universe.** ~530 discovered warrant symbols are browsable by
  search; only a handful have verified contract terms.
- **Active** now means a genuinely auditable origin — an explicit `evidence_level` or a
  provenance block. Hand-seeded strikes with neither are `UNKNOWN`, not `ACTIVE`.
- **Realtime tracked set** is capacity-limited (`FIINQUANT_MAX_REALTIME_SYMBOLS`, currently
  33) and driven by connected clients' dashboards. Metadata and history scale beyond it;
  realtime does not.
- **Default demo universe** (`GET /api/instruments/default-universe`): a curated,
  all-`VERIFIED_CURRENT` set — `CHPG2602`, `CVPB2615`, their underlyings, and `VNINDEX`.
  `CTCB2601` (`CONFLICTING`) stays reachable by search as fail-closed evidence, out of the
  default.

## 8. UI data contract (for the visual redesign)

The frontend never re-implements market logic. For every row/value the UI reads:

```
value                         (already in canonical units)
provenance.quote|book|analytics: { state, source, asOf, sessionDate, stale }
displayState                  LIVE | LAST_SESSION | MIXED | UNAVAILABLE
```

Plus, per instrument: `metadataVerification` (`VERIFIED_CURRENT | CONFLICTING | STALE |
UNVERIFIED`), `dataQuality` (`COMPLETE | PARTIAL`), `quantAvailable`. The dense table should
stay quiet (a muted marker for anything not `VERIFIED_CURRENT`); the detail drawer carries
the full provenance and warnings.
