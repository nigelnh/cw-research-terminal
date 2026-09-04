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
| Backend test suite | 1,181 passed; 21 skipped; one upstream Starlette/httpx deprecation warning |
| Frontend test suite | 36 files; 280 tests passed |
| Backend byte-code compilation | Passed |
| Frontend typecheck and production build | Passed; Vite reported the existing large-chunk/deprecated-option warnings |
| Browser — Dashboard | Rendered on the allowed local origin; explicit `CLOSED`, `OFFLINE`, and overview-unavailable states; no error overlay |
| Browser — Research | Registry rendered 33 rows from the public metadata path |
| Browser — Instrument Detail | Drawer and STATS rendered; after provider retries, chart changed from loading to `no daily history`; no page error |
| Health endpoint | HTTP 200; `provider=fiinquant`, `authenticated=false`, `market_phase` present, realtime streams disconnected |

The browser run intentionally used no market-data fixture. Expected HTTP 503 responses
from provider-backed endpoints were visible because no local FiinQuant credentials are
configured; the UI degraded without fabricating values.

## Remaining live validation

Credentialed FiinQuant validation was not run on this machine because no FiinQuant secrets
are configured. After credentials are supplied through environment/secret storage, compare
FiinQuant with a second source at the same session, timestamp, unit, and definition. Record
scope differences for volume/value rather than modifying data to force agreement. Validate
at least one actual match, one book-only update, one lunch snapshot, ATC, the 15:00 close,
and a reconnect/backfill cycle.

The HOSE phase schedule used here is cross-checked against the VPS cash-equity trading-hours
reference: <https://vps.com.vn/ca-nhan/ho-tro/cau-hoi-thuong-gap/khung-gio-giao-dich-chung-khoan-co-so>.
