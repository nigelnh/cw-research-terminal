# Vnstock-js hybrid market-data plan

Date: 2026-09-09

## Goal

Use the public source map exposed by `ttqteo/vnstock-js` to close the terminal's remaining
live-data gaps without creating a second browser-side market truth. The backend remains the
only owner of upstream connections, session decisions, normalization, caches, history and
AI context.

This integration does not run the JavaScript package as a sidecar. Its useful live protocol
is small and Apache-2.0 licensed, while its Vietcap/history/company sources overlap the
existing Python Vnstock provider. Porting the validated SSI wire contract into the Python
provider avoids a second process, a second cache, and cross-runtime session races.

## Source and capability audit

| Capability advertised by vnstock-js | Existing terminal state | Decision |
|---|---|---|
| SSI realtime matched price and three bid/ask levels | KBS board polling every 5s; canonical 3-level book already modeled | Add SSI WebSocket as primary low-latency observation; retain KBS recovery polling |
| OHLCV 1m, 5m, 1H, 1D, 1W, 1M | Provider/history contract already supports intraday and daily reads, aggregation preserves timeframe | Keep existing KBS/VCI history path and its RAW/ADJUSTED policy |
| Price board and top movers/volume | Session-scoped board, top stock/CW volume and price state already shipped | Keep terminal ranking logic; do not add an independent ranking cache |
| Company profile, events and news | VCI profiles/ratios plus persisted HOSE, SSI and VNDirect enrichment already shipped | Keep the richer persisted pipeline; use provider scopes as fallbacks only |
| Financial statements and ratios | Recent provider ratios and persisted disclosure events shipped; full statements are not part of a CW pricing input | Preserve ratios and event evidence; full statement UI remains product work, not a feed outage fix |
| Listings, groups and ICB | Exchange listing and index groups already drive overview/universe | Keep current provider boundary and per-group failure isolation |
| Screening | Watchlist filters and quant ranking exist; generic equity PE/ROE screener is outside the CW terminal flow | Do not add a parallel product surface in this change |
| Market breadth and liquidity | Breadth shipped; exchange-wide liquidity/foreign flow missing from contract | Add session-scoped derived totals with coverage and provenance |
| Gold and FX | No consumer in the CW pricing or research flow | Do not introduce unrelated commodity state into the terminal |
| Technical indicators and `aiContext()` | EMA/VWAP chart overlays; BSM/IV/Greeks/HV; canonical AI tools already shipped | Keep calculations over canonical bars; add market-wide context tool rather than accepting a second precomputed truth |
| MCP, CLI and filesystem watchlist | The web app has its own API, CLI workflows and persisted watchlist | Do not install end-user CLI/MCP state inside the production server |

## Implemented architecture

```text
SSI iBoard WebSocket ─┐
                      ├─ VnstockProvider ─ canonical events ─ MarketState ─ API/WS/UI/AI
KBS board/tape poll ──┤        │
VCI/KBS history ──────┘        └─ per-source health, coverage and provenance
```

The push channel contributes:

- receipt-timed matched-price observations in raw VND;
- cumulative volume/value;
- full bid/ask levels 1-3;
- its own connection, reconnect, parse-error and observed-symbol metrics.

It does not contribute REF, ceiling/floor, session OHLC, an authoritative exchange
timestamp, or adjusted history because those fields are not established by the public
frame. KBS/VCI remain authoritative for those groups.

The matched-lot field repeats on book updates and has no usable trade id in the captured
schema. It updates the quote but is deliberately not persisted as a time-and-sales print.
The KBS intraday endpoint remains the confirmed tape source.

## Session, ordering and cache rules

- The canonical trading calendar assigns the session at server receipt time. SSI messages
  are accepted only while the selected HOSE session is active.
- The subscription generation rejects frames from a socket replaced by a newer symbol set.
- MarketState rejects older timestamps. The KBS recovery poll cannot roll a newer SSI
  observation backwards.
- A full book snapshot explicitly clears a price level that becomes empty. This prevents a
  disappeared order from surviving in UI, liquidity and IV inputs.
- Push coverage resets at display-session rollover and is reported separately for stocks
  and CWs. No stock tick is evidence that CW push coverage exists.
- Overview liquidity and foreign flow accept only KBS rows whose provider trading date
  equals the display session. Values include observed/expected counts and coverage.

## Connection and failure policy

- The SSI socket opens only during active HOSE matching phases and pauses before open,
  during lunch, after close, on weekends and holidays.
- A 60-second in-session deadman detects a connected-but-silent channel.
- Reconnect delay starts at 3 seconds and doubles to a 60-second cap.
- SSI failures stay in the `realtime` feed scope. KBS quote/history/tape remain usable.
- The HTTP upgrade currently rejects aiohttp's default Python User-Agent with 403. An
  explicit honest `CWTerminal` User-Agent succeeds; no token, cookie or Origin is used.
- `/api/market/health` exposes the hybrid transport, socket state, message/quote counts,
  parse errors, reconnect count, session and the exact observed symbol set.

## Delivery stages

### Stage 1 — live quote and book (implemented)

- SSI parser and subscription contract;
- backend-owned session-aware socket;
- canonical trade/book mapping and raw-VND normalization;
- full-book empty-level clearing;
- hybrid health and per-asset coverage;
- captured-frame, generation and order-book regression tests.

### Stage 2 — market overview and AI (implemented)

- HOSE total volume/value derived from current-session constituent rows;
- foreign buy/sell/net volume with coverage;
- market metrics retained through overview cache session validation;
- `get_market_context` AI tool using the same shared overview as the dashboard.

### Stage 3 — production acceptance (requires an active session)

- prove SSI ticks for equities and separately for covered warrants;
- compare SSI matched price, cumulative volume and all six book levels against KBS for a
  liquid stock and CW over at least 15 minutes;
- suspend/resume through lunch and verify one socket owner after subscription changes;
- force a socket failure and confirm KBS keeps quotes available while realtime health alone
  degrades;
- verify Railway health counters and browser flow Watchlist → STATS → QUANT → book → AI.

If SSI does not publish CW frames, keep SSI for underlying equities and KBS as the CW live
source. The health coverage fields make this an observed decision rather than an assumption.

## Acceptance matrix

| Scenario | Expected result |
|---|---|
| Valid stock frame | Raw-VND trade and levels 1-3 update; source is `VNSTOCK_JS_SSI_REALTIME` |
| Valid CW frame | Same behavior, counted under CW coverage |
| Frame for an unsubscribed symbol | Ignored |
| Frame from an old generation | Ignored |
| Malformed/short frame | Ignored and parse counter increments |
| Empty level in full snapshot | Previous price cleared and quantity becomes zero |
| SSI 403/network/silence | Scoped realtime degradation and paced reconnect; KBS remains active |
| Prior-session overview cache | Excluded after 08:00 rollover |
| Pre-open market metrics | Unavailable rather than zero totals |
| Partial constituent board | Totals labelled partial with observed/expected coverage |
| AI asks about breadth/foreign flow | Reads `APP_MARKET_OVERVIEW`, not a watchlist-derived estimate |

## Deployment configuration

```text
MARKET_DATA_PROVIDER=vnstock
VNSTOCK_ENABLED=true
VNSTOCK_REALTIME_ENABLED=true
VNSTOCK_REALTIME_URL=wss://iboard-pushstream.ssi.com.vn/realtime
VNSTOCK_REALTIME_DEADMAN_SECONDS=60
VNSTOCK_REALTIME_RECONNECT_BASE_SECONDS=3
VNSTOCK_QUOTE_POLL_SECONDS=5
VNSTOCK_TAPE_SWEEP_SECONDS=120
```

No new secret or Node runtime dependency is required. The existing Vnstock API key remains
server-side for Python KBS/VCI calls.

## Validation completed

- Backend: `1534 passed, 20 skipped`.
- Frontend: `451 passed`; TypeScript and production Vite build passed.
- Focused Pyright on the new SSI provider and AI integration: zero errors.
- Focused Ruff on the new SSI parser and production monitor: passed.
- Live HTTP upgrade: default aiohttp User-Agent returned 403; the explicit product
  User-Agent opened the socket and received the expected subscription acknowledgement.
- Repository-wide Pyright still reports the pre-existing optional-type debt documented by
  the project; the files introduced by this integration are clean under the focused check.

## Evidence boundary

The upstream source and captured fixture prove the subscription envelope and field layout.
A live 2026-09-09 lunch-break probe proved the WebSocket upgrade and subscription
acknowledgement with the explicit product User-Agent. It could not prove quote delivery or
CW coverage because matching was paused; those are Stage 3 acceptance items.

Sources:

- [vnstock-js repository](https://github.com/ttqteo/vnstock-js)
- [vnstock-js realtime source](https://github.com/ttqteo/vnstock-js/tree/master/src/realtime)
- [Vnstock Python migration report](./VNSTOCK_MIGRATION_20260908.md)
- [Third-party notices](../THIRD_PARTY_NOTICES.md)
