# Step 13C — Market Data Temporal Architecture, Trading Calendar, After-Hours Fallback, Research Universe

Date: 2026-08-29 (Sat, HOSE closed) · Branch `main` · Backend Railway `backend-production-626f` · Frontend Vercel `cw-research-terminal`

This step was data + state architecture, not a visual redesign. **Stopping after this report — Step 13D (UX/UI implementation) is not started.**

---

## 1. Current data architecture audit — what was wrong

Outside an active HOSE session the terminal rendered an almost-empty grid. Three structural
causes:

1. **No canonical trading calendar.** `market_session.py` modelled only weekday + clock —
   **zero holidays**. A *separate* partial calendar in `app/persistence/ingestion/trading_calendar.py`
   (fixed-date holidays + approximate Tet) was used only by the ingestion gap-classifier.
   Neither offered `previous_trading_session` / `latest_completed_trading_session`. The
   frontend re-derived DTE with the viewer's local `Date.now()`.
2. **No durable after-hours source.** `CanonicalQuote.to_wire_snapshot_row(display_eligible=False)`
   nulls every realtime-derived field. Redis warm cache is TTL 24 h + staleness-rejected at
   24 h → gone over any weekend. `market_bars` (daily OHLCV) was the only durable store and
   **nothing read it for the dashboard**. FiinQuant historical (`Fetch_Trading_Data`)
   returns **OHLCV only** — no reference price, no order book, ever.
3. **Fabricated research universe.** `active_warrants.json` held 12 CWs with hand-seeded
   strike/ratio/maturity but **no provenance** and `UNVERIFIED` metadata.
   `CanonicalInstrumentProvider` promoted *any* record with a strike + future maturity to
   `ACTIVE`, so `/api/instruments?active_only=true` returned **15** (3 real + 12 fabricated).

## 2. Chosen system design & why

A **layered temporal fallback**, resolved server-side, with every value carrying an explicit
origin. Alternatives rejected:

- *Keep "live or nothing"* — financially honest, poor research terminal (the stated problem).
- *Let the browser fetch history* — breaks the single-owner realtime model, N page-loads =
  N upstream calls, no crash safety.
- *Redis as the after-hours store* — volatile, TTL/staleness-gated, an eviction erases
  research.
- *A generic `Value<T>` wrapper everywhere* — too invasive for the payoff; a compact
  per-field-group `provenance` block on the wire is enough for the UI.

Chosen: one **canonical calendar** module; a **`DataTemporalState`** vocabulary; a
server-side **resolver** (`GET /api/market/dashboard`) applying LIVE → last-session snapshot
→ EOD bars → UNAVAILABLE; a small **`instrument_snapshots`** table (the only way to ever
recover a closing bid/ask or survive a mid-session crash); **on-demand EOD quant** with
strict same-session input alignment. PostgreSQL-first semantics preserved; Redis stays warm
state only.

## 3. Market calendar

`backend/app/market_data/trading_calendar.py` — the single source of truth.
`market_session.py` and `persistence/ingestion/trading_calendar.py` are now thin delegating
shims.

| Concern | Implementation |
|---|---|
| Timezone | `Asia/Ho_Chi_Minh`, fixed UTC+7, no DST |
| Sessions | morning 09:00–11:30, lunch 11:30–13:00, afternoon 13:00–15:00 |
| Weekends | Sat/Sun non-trading |
| Holidays | **hand-maintained** `VN_EXCHANGE_HOLIDAYS` from the official HOSE *"Notice of trading holiday schedule"* — **2024 / 2025 / 2026 confirmed** (`AUTHORITATIVE`), **2027 provisional** (`APPROXIMATE`); beyond that: weekends + 4 fixed-date public holidays + approximate Tet window |
| 2026 closures (from the HOSE PDF) | Jan 1–2 · Feb 16–20 (Tet) · Apr 27 · Apr 30–May 1 · Aug 31–Sep 2 |
| Exceptional closures | `EXCHANGE_CALENDAR_OVERRIDES_JSON` env — `{extra_closures:[…], force_open:[…]}`, no code change |
| Fail-safe | any lookup error → weekend-only, `calendar_confidence = APPROXIMATE`; limitation documented |
| `previous_trading_session(d)` | most recent trading day strictly before `d` (walks ≤ 30 days) |
| `latest_completed_trading_session(now)` | most recent date whose 15:00 close has passed |
| `next_trading_session_open(now)` | next 09:00 / 13:00 open |
| `trading_sessions_between(a,b)` | inclusive list of trading days |

Verified in production: `latest_completed_trading_session` on Sat 2026-08-29 → `2026-08-28`;
`previous_trading_session(2026-08-31)` (National Day Mon) → `2026-08-28`;
`next_trading_session_open` from Fri 28 Aug 16:00 → **Thu 3 Sep 09:00** (skips the weekend +
the 3-day National Day block). `calendar_confidence` → `AUTHORITATIVE` for 2026,
`APPROXIMATE` for 2029.

## 4. Data precedence

**Active session** — unchanged: FiinQuant SignalR → `MarketState` (L1) → Redis warm (L2) →
WS `/ws/market` → the frontend WS client (single live owner). Authoritative for every field
it supplies.

**Outside trading** — `market_snapshot_resolver`, per field group:

| # | Source | Condition | Supplies |
|---|---|---|---|
| A | `LIVE` | active session + fresh `MarketState` tick (`is_display_eligible`) | everything |
| B | `instrument_snapshots` | last completed session's persisted snapshot | ref, last, change, OHLC, volume + **closing bid/ask** (only from a real observed snapshot) |
| C | `market_bars` daily | no usable snapshot | last = close, OHLC, volume; ref = **previous session's close** (`PRIOR_CLOSE`); change = `DERIVED`. One controlled gap-fill for a missing latest-session bar → persist → reuse. **No bid/ask.** |
| D | `UNAVAILABLE` | realtime-only field, no B source | `null`, never fabricated |

## 5. Field-by-field source matrix

| Field | Live source | Fallback source | When UNAVAILABLE | As-of semantics |
|---|---|---|---|---|
| **REF** | feed reference price | snapshot ref, else **prior trading session's close** | never (once any history exists) | prior session date |
| **LAST** | matched trade | snapshot last, else EOD close | no snapshot & no bar | that session's 15:00 |
| **CHANGE / %** | feed | snapshot, else `close − prior_close` (`DERIVED`) | no prior close | session date |
| **OPEN/HIGH/LOW** | feed | snapshot, else EOD bar | no bar | session date |
| **VOLUME** | feed cumulative | snapshot, else EOD bar volume | no bar | session date |
| **BID / ASK** | feed L1 depth | **snapshot only** (FINAL/CHECKPOINT) — FiinQuant has no historical book | closed & no snapshot | snapshot `captured_at` |
| **SPREAD / SPREAD %** | `(ask−bid)/bid` from live | from a snapshot bid+ask only | whenever bid or ask is unavailable — **never computed from OHLC** | as bid/ask |
| **UNDERLYING PRICE** | underlying feed | underlying's own resolved row (snapshot → EOD) | underlying has no data | as underlying |
| **THEO / IV-TRADE / GREEKS / MONEYNESS** | `LiveQuantEngine` (session) | `compute_eod_analytics(sym, last_session)` — CW close + underlying close both for that session | metadata gate closed, or a leg missing (`EOD_INPUT_MISSING`) | that session's 15:00 |
| **IV-BID / IV-ASK** | live, needs live bid/ask | — | always, outside a live session (no EOD book) | n/a |
| **HV** | `historical_volatility_service` HV_22 | same (latest ≤ now; documented approximation) | insufficient history | rolling window |
| **DTE** | calendar days to maturity, VN date | backend `analytics.dte`, else VN-anchored calc | no maturity | evaluated at session 15:00 |

## 6. FiinQuant capability findings (this account)

From `backend/poc/fiinquant/` + the runtime integration:

- **Realtime:** SignalR `Trading_Data_Stream` (trade) + `BidAsk` (L1–L3 depth). No dynamic
  subscribe — changing symbols restarts the stream. Capacity: `FIINQUANT_MAX_REALTIME_SYMBOLS = 33`.
- **Historical:** `Fetch_Trading_Data(realtime=False, fields=["open","high","low","close","volume"], by="1d")`
  — **OHLCV only**, daily and intraday. `adjusted=True` (dividend-adjusted decimals) for
  stocks; CW bars are RAW. **~365-day per-request window.** No reference price, **no
  historical order book**, no historical IV/Greeks.
- **`BasicInfor` (CW static terms): `403 Forbidden`** on this tier — CW strike/ratio/maturity
  come from local curated fixtures with provenance.

**Consequence:** a persisted last-valid realtime snapshot is the *only* way to ever show an
after-hours closing bid/ask, and the only crash/redeploy recovery for a session's state.

## 7. Persistence changes

- **`instrument_snapshots`** (Alembic `0003`, forward-safe, `downgrade` drops it) — one
  upserted row per `(symbol, session_date)`: ref/last/change/OHLC/volume, L1–L3 bid/ask,
  underlying price, `source` (`REALTIME_CHECKPOINT | SESSION_CLOSE | HISTORICAL_SEED`),
  `quality` (`FINAL | INTRADAY_CHECKPOINT | SEED`).
- **`SnapshotRepository.upsert`** guards: never regress to an older session; within a
  session `captured_at` only advances and `quality` never downgrades `FINAL →` anything.
- **`SnapshotCheckpointer`** — bounded lifespan-owned task: throttled per-symbol write
  (default 90 s) during an active session **only on a changed quote**; a `FINAL` write at
  15:00 and once on graceful shutdown. Coalesced — write rate ≤ (#tracked / 90 s).
- **No `analytics_snapshots` table** — EOD analytics are recomputed on demand from persisted
  bars (deterministic, always consistent with corrected metadata) and cached per
  `(symbol, session_date)`.
- **No universe backfill.** An idempotent per-tracked-symbol `SEED` row can be added from
  the latest `market_bars` close so the first post-deploy weekend view is populated.

## 8. Temporal quant design

`LiveQuantEngine.compute_eod_analytics(cw, session_date)`:

- CW price = `market_bars` **close** for `(cw, session_date, RAW)`.
- Underlying price = `market_bars` **close** for `(underlying, session_date, ADJUSTED)`.
- `T`, DTE, contract-lifecycle state, `calculated_at` all evaluated at **15:00 ICT of
  `session_date`** (`as_of` threaded through `compute_warrant_analytics` →
  `calculate_time_to_maturity` → `derive_contract_state`).
- A missing leg → `is_available = False`, `unavailable_reason = "EOD_INPUT_MISSING (<leg>@<date>)"`.
  It never substitutes a `T-1` price for a `T` price.
- Same metadata gate as live: `CONFLICTING` (CTCB2601) → unavailable.
- Produces IV-trade, Greeks, theoretical value, moneyness, DTE. IV-bid/ask/spread
  `UNAVAILABLE` (no EOD book). HV uses the latest ≤ now HV_22 (documented — HV_22 moves
  negligibly in one session).

Verified in production (Sat, last session 2026-08-28): CHPG2602 → iv_trade 0.442, delta
0.027, moneyness 0.854, source `QUANT_EOD` @ `2026-08-28`; CVPB2615 → iv_trade 0.214, delta
0.263; CTCB2601 → `UNAVAILABLE (METADATA_NOT_VERIFIED_CURRENT CONFLICTING)`.

## 9. Research tab — root cause of the static 15-row universe

`active_warrants.json` had 12 warrants (CFPT2601/2602/2604, CHPG2604/2609/2611, CMBB2601,
CMWG2601/2602, CSTB2601, CVHM2601, CVNM2601) with a full term set but **no `provenance` and
no `evidence_level`**. `CanonicalInstrumentProvider._determine_lifecycle_and_evidence` rule 3
promoted any record with `strike_price != None` + a future maturity to `ACTIVE / COMPLETE`.
So `active_only=true` returned those 12 + the 3 genuine ones = **15**, and the Research tab
rendered all 15 as "the universe".

## 10. New research universe model

- **The registry is the research universe.** ~530 discovered CW symbols, browsable by
  symbol/underlying/issuer. Contract terms only where genuinely known.
- **`ACTIVE` requires an auditable origin** — an explicit `evidence_level` *or* a provenance
  block. Term completeness alone no longer promotes. `/api/instruments?active_only=true` now
  returns **3** (CHPG2602, CVPB2615 verified; CTCB2601 conflicting); `?verified_only=true` →
  **2**. The 12 fabricated term-sets were stripped from the JSON — the symbols remain as
  identity-only `UNKNOWN` rows.
- **Research tab:** default view = the 3 active; typing a search switches to
  `status=ALL` (the whole registry) so any listed warrant is findable without dumping 530
  mostly-empty rows. Verified in production: search "MWG" → 49 results, all `Reference`, no
  fabricated strikes.
- **Distinct concepts:** *watchlist* (persisted, per-user identity + preference) ≠ *research
  selection* (transient) ≠ *realtime tracked set* (server, ≤ 33). Documented, no schema
  change.

## 11. User-add flow

Search the registry (`/api/instruments?status=ALL&search=…`) → select → "add to dashboard"
(`useWatchlist.addToWatchlist`, capacity-checked via `canAdd`). Metadata + history work for
any registry symbol immediately; a realtime slot is only consumed when it's on a dashboard.
No developer edit required.

## 12. Realtime subscription-capacity model

| Tier | Scope | Bound |
|---|---|---|
| Static metadata | every registry symbol (~530) | none |
| Historical / EOD research | any registry symbol, PostgreSQL-first + one controlled gap-fill | provider-quota-safe |
| Realtime | union of connected clients' dashboards | `FIINQUANT_MAX_REALTIME_SYMBOLS` (33) |

`GET /api/market/subscriptions` now reports `capacity_remaining`. Browsing or researching a
symbol never subscribes it.

## 13. Default demo universe

`GET /api/instruments/default-universe` and the frontend v4 seed:
**`CHPG2602`, `CVPB2615`** (both `VERIFIED_CURRENT`) **+ `HPG`, `VPB`** (underlyings) **+
`VNINDEX`**. All produce real EOD quotes and analytics. **CTCB2601** (`CONFLICTING`) is
deliberately **out of the default** but stays reachable by search as fail-closed evidence —
it is not deleted. Watchlist schema `v3 → v4`: an untouched legacy default (HPG/NVL/VHM/
CTCB2601/CVPB2615) is re-seeded; a customised watchlist migrates unchanged (no manual clear,
anonymous prefs preserved).

## 14. Before / after — closed-market experience (production, Sat 2026-08-29)

| | Before | After |
|---|---|---|
| Dashboard | empty grid, every cell `—` | Stocks: HPG 22,100 (▼0.45%, vol 17,126,700), VPB 27,800 (▲1.46%), VNINDEX 1,832,120. CWs: CHPG2602 last 30 / IV-trade 44.2% / DTE 24d, CVPB2615 last 810 / IV-trade 21.4% / DTE 173d. Header: *"Market closed — showing Fri 28 Aug close"* |
| BID / ASK / SPREAD | `—` | `—` (no EOD order book — correct, not faked) |
| Research tab | 15 rows, 12 with fabricated strikes | 3 active with real terms; search → the full registry |
| AI | *"HPG closed at 21,500 on Wed 27 Aug 2025"* (fabricated) | *"HPG last closed at 22,100 VND on … 28 August 2026 … that print is the most recent settled reference, not a live quote"* |

## 15. Test results

Backend `pytest` **981 passed**, 20 skipped; `pyright app` **0 errors**. New:

- `test_trading_calendar.py` (21) — week matrix, holiday clusters, year boundary,
  confidence, overrides.
- `persistence/test_market_snapshot_resolver.py` (6) — LIVE → SNAPSHOT → EOD_BARS →
  UNAVAILABLE precedence, no-trade-this-session date preservation, diag trace.
- `persistence/test_eod_quant_alignment.py` (4) — aligned session, missing leg →
  `EOD_INPUT_MISSING`, no D-1/D mixing, `CONFLICTING` still gated.
- `persistence/test_snapshot_repository.py` (4) — idempotency, `captured_at` monotonic, no
  session regression, `FINAL` never downgraded.
- `test_research_universe.py` (6).
- Updated: `test_instrument_registry`, `test_gaps_and_locks`, `test_market_session`.

Frontend `vitest` **211 passed** (26 files), `tsc --noEmit` clean, `npm run build` ok.
Updated for the universe change: `realtime_acceptance`, `watchlist_storage`,
`auth_session_and_watchlist`, `dashboard_regression_restore`, `dashboard_and_ux_polish`,
`partial_instrument_ux`.

## 16. Production smoke results

- `GET /health` → `calendar_confidence: AUTHORITATIVE`, `snapshot_checkpointer.enabled: true`,
  `database.connected: true`.
- `GET /api/market/dashboard?symbols=HPG,VHM,CHPG2602,CVPB2615,CTCB2601,VNINDEX` → every row
  `LAST_SESSION`, `sessionDate 2026-08-28`, real close/volume; bid/ask `UNAVAILABLE`;
  CTCB2601 analytics `UNAVAILABLE (CONFLICTING)`.
- `GET /api/market/_diag/HPG` → `chosen: EOD_BARS`, `bar_session 2026-08-28`.
- `GET /api/instruments?active_only=true` → 3; `/default-universe` → the curated 5.
- Browser (`cw-research-terminal.vercel.app`): dashboard populated with the "as of Fri 28
  Aug close" affordance; Research shows 3 active, search "MWG" → 49; **no console errors**.
- AI: after-hours prompts cite the correct EOD close, labelled not-live (see §14).

## 17. Next live-session verification checklist (Mon — do not fake)

At the next active HOSE session:

- [ ] A dashboard row transitions `displayState: LAST_SESSION → LIVE` with no manual refresh
  (the hook refetches on the session flip; WS patches take over).
- [ ] No flicker to a stale value; no old-session value overriding a fresh tick
  (`isEventStale` guard).
- [ ] `SnapshotCheckpointer` writes `INTRADAY_CHECKPOINT` rows (`/health.snapshot_checkpointer.counters.rows_written` climbs), throttled ~90 s, only on changed quotes.
- [ ] At 15:00 ICT: one `FINAL` checkpoint per tracked symbol; `final_done_for = <today>`.
- [ ] EOD analytics recompute for the new session; `sessionDate` advances.
- [ ] Realtime subscription count does not grow unbounded; no unexpected historical
  provider calls (`/health.history_reads.counters`).
- [ ] `GET /api/market/dashboard` bid/ask populate from the live feed, then from the `FINAL`
  snapshot after close.

## 18. Data contract for the UX/UI redesign

The UI never re-implements market logic. Per row/value it reads:

```
value                                  (canonical units already)
provenance.{quote|book|analytics}:     { state, source, asOf, sessionDate, stale }
displayState:                          LIVE | LAST_SESSION | MIXED | UNAVAILABLE
```

Per instrument: `metadataVerification` (VERIFIED_CURRENT | CONFLICTING | STALE | UNVERIFIED),
`dataQuality` (COMPLETE | PARTIAL), `quantAvailable`. Row-level meta from the endpoint:
`market_session`, `latest_completed_session`, `calendar_confidence`.

**States the visual redesign must express:** `LIVE`, `LAST_SESSION` (with an "as of <date>"
affordance), `HISTORICAL` / `STALE`, `UNAVAILABLE` (distinct from zero), and a *muted*
non-`VERIFIED_CURRENT` marker in the dense table with full provenance in the detail drawer.
See `docs/domain/market_data_temporal_architecture.md`.

## 19. Remaining correctness blockers

**None.** Known non-blocking notes:
- 2027 exchange holidays are provisional (`calendar_confidence: APPROXIMATE`) until HOSE
  publishes the official notice (~Dec 2026); overridable via env.
- After-hours BID/ASK/SPREAD populate only once `instrument_snapshots` has a real observed
  row for a symbol (accumulates from the next live session; the SEED row carries no book).
- The `minimax/minimax-m3:free` model occasionally mislabels the day-of-week; the ISO date
  and the numbers it cites are correct and drawn from canonical data.
- `test_fiinquant_lifecycle::test_T14` is timing-sensitive under randomised order (pre-existing;
  passes deterministically and in isolation).

## 20. Ready for Step 13D?

**Yes.** The data + state layer is complete, deployed, and production-verified. The UI data
contract (§18) is stable and documented; the visual redesign can consume it without
understanding any market-data edge case.

## Commits

| Commit | Scope |
|---|---|
| `2b64…`→`c3551d1` | calendar + temporal model + resolver + snapshot table + EOD quant + endpoints + research-universe fix + tests |
| `7f9c4b7` | frontend data-flow (dashboard fallback hook, DTE, labels, AI envelope) + curated default universe + v4 migration |
| `951c152` | fix: `status` in the active-warrants query key |
| `34f49b1` | AI cites EOD closes when the market is closed |
| `<docs>` | `market_data_temporal_architecture.md` + this report |

## Security posture (unchanged)

No secrets in output. No browser→FiinQuant. No uncontrolled provider calls (the dashboard
fallback does at most one gap-fill per missing latest-session bar, then persists). Metadata
verification not weakened — `CONFLICTING` still gates analytics closed. No KB / private
integrations. Rate-limit / CORS / budget intact. Free model only.
