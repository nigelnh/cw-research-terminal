# FiinQuant integration report — 2026-09-03

## Scope and source policy

FiinQuant is the canonical provider for realtime quotes, order book, reference prices,
historical OHLCV, session volume, and session trading value. Public sources remain in use
only for covered-warrant metadata, news, and corporate actions where FiinQuant does not
provide the required record.

No broker, screener, RRG, MCP, fixture, mock provider, or seeded market price is connected
to the production market-data path.

## Canonical field contract

| Terminal field | FiinQuant field | Meaning / unit |
|---|---|---|
| `TRD_PRC` | `Close` / actual matched-price alias | Most recent actual match; VND for securities, index points for indices |
| `TRD_AMT` | `MatchVolume` | Quantity of the most recent match |
| `VOLUME` | `TotalMatchVolume` | Cumulative matched quantity for the session |
| session trading value | `TotalMatchValue` | Cumulative matched value in VND |
| historical trading value | `value` | Trading value for the historical bar in VND |
| `REF` | realtime `Reference`; historical `get_ceilingfloor.referenceValue` | Reference price for the stated session |
| `CEIL` / `FLOOR` | realtime reference group; historical `get_ceilingfloor` | Session-specific price limits |

The FiinQuant adapter normalizes aliases, finite numeric values, timestamps, and timezone
once. Numeric zero is valid; absence remains `null`. Trade, order-book, and reference
timestamps are independent, so a newer book/reference event cannot make an old trade look
live. Provider `MarketStatus` is retained as an opaque value until its code meanings are
verified.

FiinQuant pre-open `Close/OHLC=0` resets are not executions: zero totals remain valid, but
they do not create a last trade, trade timestamp, last-match quantity, or candle.

## Session, persistence, chart, and analytics

- HOSE phases are resolved in Asia/Ho_Chi_Minh time: pre-open, ATO (09:00–09:15), morning
  continuous, lunch, afternoon continuous, ATC (14:30–14:45), post-close negotiated
  trading, and closed at 15:00. Existing coarse session fields remain compatible.
- During ATO, book-only data is valid without a trade. Lunch and other same-session pauses
  retain an explicit `SESSION_SNAPSHOT`; previous-session values are never relabelled live.
- Snapshot, Redis, and checkpoint paths preserve `TRD_AMT`, `CEIL`, `FLOOR`, and the three
  timestamp groups. Alembic revision `0007_fiinquant_semantics` adds nullable columns only
  and performs no guessed historical backfill.
- Intraday bars are built only from actual trade events already received by the single
  SignalR owner. They are bucketed in Vietnam time, de-duplicated, and emitted through the
  existing WebSocket as incomplete `bar_patch` updates. REST history remains the
  seed/reconciliation source.
- The frontend no longer creates a candle from session OHLC plus the full-day cumulative
  volume. RAW intraday bars and ADJUSTED series are not mixed. EMA preserves gaps, VWAP
  resets by intraday session, and relative charts align on common timestamps.
- Historical volatility uses the last included session as `as_of`; future observations and
  cross-session covered-warrant/underlying pairs are rejected. Spread percentage uses the
  midpoint consistently in the resolver, UI payload, quant data, and AI context.
- Reload hydration is snapshot-first: `/api/market/dashboard` resolves quote/book/reference
  independently from `/api/market/dashboard/analytics`, so slow EOD quant work cannot blank
  ready persisted prices. Multi-tab EOD requests are single-flighted; unavailable results
  have a short TTL so a newly ingested daily bar can recover without a process restart.
- Legacy book-only snapshots recover actual historical closes through a separate Redis
  namespace keyed by symbol, price basis, and completed session. The bounded server universe
  is warmed at startup; history-derived prices keep `EOD_BARS` provenance rather than being
  relabelled as observed trades. Same-session snapshot upserts preserve known values when a
  later partial checkpoint contains null, while legitimate zero values remain writable.
- Market Overview has a separate Redis snapshot and single-flight background refresh.
  Cold HTTP reads wait at most two seconds for provider computation; a slow refresh does
  not block warm reads or other tabs. Cache age and original observation timestamps stay
  separate, and stale cached values are explicitly labelled rather than marked live.

## Availability and fail-closed behaviour

| Field / capability | Availability rule |
|---|---|
| historical `MatchVolume` / `TRD_AMT` | Unavailable unless it was observed and persisted in a realtime snapshot; it cannot be reconstructed from daily volume |
| historical bid/ask and order-book timestamp | Unavailable unless captured in a real snapshot; FiinQuant daily history is not treated as historical book data |
| trading value on pre-migration rows | Remains `null`; migration does not infer it from price × volume |
| live quote/book/reference | Unavailable when FiinQuant is unauthenticated or disconnected; UI displays `OFFLINE` and `—` |
| MarketStatus interpretation | Raw provider value retained; no undocumented status-code mapping is applied |
| IV / Greeks / theoretical value | Unavailable when contract terms are unverified, inputs are temporally incompatible, or a required price/HV input is missing |
| complete intraday coverage after a gap | Bar patches remain marked incomplete until REST history seed/reconciliation supplies coverage |

## Verification results

| Check | Result |
|---|---|
| Backend test suite | 1,191 passed; 21 skipped; one upstream Starlette/httpx deprecation warning |
| Frontend test suite | 36 files; 282 tests passed |
| Backend byte-code compilation | Passed |
| Frontend typecheck and production build | Passed; Vite reported the existing large-chunk/deprecated-option warnings |
| Browser — Dashboard | Rendered on the allowed local origin; explicit `CLOSED`, `OFFLINE`, and overview-unavailable states; no error overlay |
| Browser — Research | Registry rendered 33 rows from the public metadata path |
| Browser — Instrument Detail | Drawer and STATS rendered; after provider retries, chart changed from loading to `no daily history`; no page error |
| Health endpoint | HTTP 200; `provider=fiinquant`, `authenticated=false`, `market_phase` present, realtime streams disconnected |

The browser run intentionally used no market-data fixture. Expected HTTP 503 responses
from provider-backed endpoints were visible because no local FiinQuant credentials are
configured; the UI degraded without fabricating values.

## Production reload verification — 2026-09-04 ICT

Production was deployed with explicit user authorization. The authenticated Railway
backend reports Redis and PostgreSQL connected, FiinQuant READY, the 30-symbol server-owned
universe restored, and Alembic revision `0007_fiinquant_semantics` applied. Redis read/write
and restore error counters were zero at verification.

Headless Chrome opened two tabs on the production Vercel domain, then reloaded both
simultaneously. Each received 30 rows with 30 positive prices. The dashboard responses
arrived in 286 ms and 445 ms on reload, versus the previously observed 13–15 seconds.
The UI displayed HPG 21,650 / volume 9,472,000 and CHPG2617 440 / volume 631,100.
No JavaScript page errors, non-aborted network failures, or error overlays were observed.
These were explicitly LAST_SESSION values during PRE_OPEN, not live executions.

After a backend restart, historical fallback cache reads recovered legacy book-only CW
snapshots without direct provider history calls. A pre-open feed reset with zero prices
no longer overwrites the last actual trade or creates a false −100% move.

## Remaining live validation

FiinQuant secrets remain absent locally; the reload checks above used the already-configured
production backend without exposing credentials. A full live comparison against a second
source at the same session, timestamp, unit, and definition remains outstanding. Record
scope differences for volume/value rather than modifying data to force agreement. Validate
at least one actual match, one book-only update, one lunch snapshot, ATC, the 15:00 close,
and a reconnect/backfill cycle.

The HOSE phase schedule used here is cross-checked against the VPS cash-equity trading-hours
reference: <https://vps.com.vn/ca-nhan/ho-tro/cau-hoi-thuong-gap/khung-gio-giao-dich-chung-khoan-co-so>.
