# Project Progress: cw-research-platform

## Completed Changes
* **Full Repository Structure Cleanup, Historical Domain Reconstruction & Architecture Reorganization**:
  * **Deep Git Archaeology & Historical Formula Lineage**:
    - Recovered and cataloged all 33 historical formulas ($F-01$ to $F-33$) with exact `SOURCE_COMMIT`, `SOURCE_FILE`, and `ACTUAL_SOURCE_EVIDENCE`.
    - Identified formulas deleted across history: $F-31$ (Stock Beta in `c0fff65:server/python_api/beta_calculator.py`), $F-32$ (Bid-Ask Spread % in `c0fff65:frontend/src/tables/cw/CWTable.ts`), $F-33$ (Issuer Market Share in `c0fff65:frontend/src/app/MarketShareTables.tsx`).
    - Cataloged 54 historical Info-tab (Position Master) spreadsheet columns and 15 Stock-tab columns.
  * **Backend Descriptive Snake_Case Renaming**:
    - Standardized generic backend filenames to self-describing snake_case: `market_data/market_state.py`, `market_data/market_subscription_manager.py`, `market_data/market_websocket.py`, `instruments/instrument_registry.py`, `quant/quant_engine.py`, `quant/historical_volatility.py`, `ai/ai_system_prompt.py`, `ai/ai_router.py`.
  * **Frontend Feature-Driven Modularization**:
    - Reorganized components into canonical feature directories: `frontend/src/features/market_overview/`, `frontend/src/features/warrant_info/`, `frontend/src/features/stock_research/`, `frontend/src/features/watchlist/`, `frontend/src/features/ai_assistant/`.
    - Retained shared UI primitives under `frontend/src/components/common/`.
  * **Legacy Reference Archival Namespace**:
    - Consolidated historical reference material into `legacy/historical_formulas/` (30 CLI scripts) and `legacy/legacy_node_server/` (Node.js/Postgres backend).
  * **Two-Stage Theoretical Fair Value Architecture**:
    - Formally documented the pipeline separating `QuantEngine` (independent volatility orchestration using $\sigma_{\text{HV22}}$) from `black_scholes.py` (pure BSM call pricing math primitive), preserving the invariant $\text{model\_price\_at\_iv\_mid} \neq \text{theoretical\_price}$.
  * **Transport-Unit Compatibility Boundary Documentation**:
    - Documented end-to-end data flow: FiinQuant Raw $\to$ `FiinQuantProvider` $\to$ `MarketState` (Canonical Raw VND) $\to$ WebSocket wire transport $\to$ Frontend mapper $\to$ `MarketQuote`.
  * **Full Verification & Zero-Regression Loop**:
    - Backend Pytest: **42/42 passed (100%)** via `PYTHONPATH=backend backend/.venv/bin/pytest backend/tests/`.
    - Frontend Vitest: **96/96 passed across 15 suites (100%)** via `npm --prefix frontend test -- --run`.
    - Frontend Production Build: **Built cleanly in 1.05s with 0 errors** via `npm --prefix frontend run build`.
    - Static Type Checking: **0 errors, 0 warnings, 0 informations** via `npx pyright backend/app backend/tests`.
    - Platform Architecture Audit: **36/36 passed (0 failures)** via `npx tsx audit/test_research_platform.ts`.

* **Transition to Realtime-Only Operation & Complete Runtime Mock Removal**:
  * **Elimination of Runtime Mock Providers & Demo Fixtures**:
    - Removed `frontend/src/data/mock/` and `frontend/src/data/fixtures/` from production runtime; relocated test doubles into isolated `frontend/src/__tests__/test_fixtures/`.
    - Removed `frontend/src/constants/index_data.ts` (hardcoded index prices) and initialized `indices` state as empty `[]`.
    - Removed `backend/app/market_data/providers/mock_market_provider.py` from the production package and isolated it in `backend/tests/fixtures/mock_market_provider.py`.
    - Updated `ProviderFactory` to resolve strictly to live backend providers (`BackendMarketDataProvider`, `BackendInstrumentProvider`, `BackendHistoricalDataProvider`, `BackendQuantProvider`) with zero mock fallback.
    - Updated `SubscriptionManager` to default unconditionally to `FiinQuantProvider`.
  * **Strict Missing Data Contract**:
    - When market data is missing/closed: all realtime-dependent values render as `—` (em-dash), never `0`, `0.00`, `NaN`, `undefined`, or fake values.
    - Covered Warrant Last is strictly actual trades only; if Bid/Ask exists without trade, `Last = —` and `IV Trade = —`.
    - Static reference metadata (strike, ratio, issuer, maturity, underlying) is preserved independently from `InstrumentRegistry`.
  * **Canonical Acceptance Universe Validation**:
    - Target universe: `HPG`, `NVL`, `VHM`, `CVHM2615` (underlying `VHM`), `CHPG2541` (underlying `HPG`).
    - Verified deduplication into exactly 5 unique realtime subscriptions `["CHPG2541", "CVHM2615", "HPG", "NVL", "VHM"]`.
  * **Comprehensive Regression Suite**:
    - Backend Pytest: **44/44 passed (100%)**.
    - Frontend Vitest: **106/106 passed across 16 suites (100%)**.
    - Frontend Production Build: **Built cleanly in 1.08s with 0 errors**.
    - Pyright Type Check: **0 errors, 0 warnings, 0 informations**.
    - Platform Audit: **36/36 passed (100%)**.

* **Corrective Universe-Scoping Pass & Explicit Three-Universe Architecture**:
  * **Strict Separation of Universe Concepts**:
    - **PRIMARY_UI_UNIVERSE**: Exactly 5 canonical symbols `["HPG", "NVL", "VHM", "CVHM2615", "CHPG2541"]`. Pre-populated as the default Personal Dashboard watchlist with zero synthetic leakages.
    - **RESEARCH_UNIVERSE**: Broader searchable/browsable catalog loaded from `InstrumentRegistry` (~400+ CWs & stocks) with 0 automatic realtime slot consumption.
    - **REALTIME_SUBSCRIPTION_UNIVERSE**: Deduplicated active subscription set (`CVHM2615 → VHM`, `CHPG2541 → HPG` resulting in exactly 5 unique symbols `["CHPG2541", "CVHM2615", "HPG", "NVL", "VHM"]`).
  * **Default Configuration Refinement**:
    - `config.defaultLiveSymbols` defaults strictly to `[]` (empty) to avoid unrequested subscriptions to `VNINDEX`/`VN30`.
  * **Comprehensive Regression & Acceptance Verification**:
    - Backend Pytest: **44/44 passed (100%)**.
    - Frontend Vitest: **109/109 passed across 16 suites (100%)**.
    - Frontend Production Build: **Built cleanly in 1.06s with 0 errors**.
    - Pyright Type Check: **0 errors, 0 warnings, 0 informations**.
    - Platform Audit: **36/36 passed (100%)**.

* **Persisted Watchlist Migration Fix (Schema Version 2)**:
  * **Root Cause Identification**:
    - Browser hydration loaded legacy version 1 watchlist data (`WATCHLIST_STORAGE_KEY_V1 = "cw-research-watchlist:v1"`) containing 6 obsolete CW symbols (`CFPT2602`, `CHPG2602`, `CFPT2604`, `CHPG2611`, `CHPG2609`, `CHPG2604`), which requested 8 realtime subscriptions (`8 / 33 live`).
  * **Deterministic Versioned Migration**:
    - Bumped storage key to `WATCHLIST_STORAGE_KEY_V2 = "cw-research-watchlist:v2"` and schema version to `CURRENT_WATCHLIST_SCHEMA_VERSION = 2`.
    - Added one-time migration in `WatchlistStorage.loadWatchlist()`: legacy V1 persisted state automatically migrates to the exact 5 primary symbols (`HPG`, `NVL`, `VHM`, `CVHM2615`, `CHPG2541`) and deletes obsolete V1 key.
    - Subsequent reloads preserve user edits under V2 without continuous reset.
  * **Comprehensive Regression & Acceptance Verification**:
    - Backend Pytest: **44/44 passed (100%)**.
    - Frontend Vitest: **112/112 passed across 16 suites (100%)**.
    - Frontend Production Build: **Built cleanly in 1.05s with 0 errors**.
    - Pyright Type Check: **0 errors, 0 warnings, 0 informations**.
    - Platform Audit: **36/36 passed (100%)**.

* **Canonical WebSocket Route Normalization & Connection Fix**:
  * **Root Cause Identification**:
    - `frontend/.env` set `VITE_WS_URL=ws://localhost:8501` (omitting the pathname `/ws/market`).
    - `config.ts` evaluated `if (!wsUrl)` which was bypassed because `rawWsUrl` was truthy, causing the browser `WebSocket` constructor to connect to `ws://localhost:8501/` (root).
    - FastAPI rejected `WebSocket /` with `403 Forbidden` because the market WebSocket is registered exclusively at `/ws/market`.
  * **Canonical URL Normalization & Configuration Hardening**:
    - Created `normalizeWsUrl` and `normalizeApiUrl` in `frontend/src/config.ts` to deterministically ensure WebSocket endpoints resolve to `/ws/market`.
    - Updated `BackendWebSocketClient` to use `normalizeWsUrl` with default fallback `ws://localhost:8501/ws/market`.
    - Updated `frontend/.env` and `frontend/.env.example` to `VITE_WS_URL=ws://localhost:8501/ws/market`.
    - Replaced `WebSocket.OPEN` references with numeric constants (`WS_OPEN = 1`) for universal Node/browser test environment portability.
  * **Comprehensive Regression & Acceptance Verification**:
    - Backend Pytest: **44/44 passed (100%)**.
    - Frontend Vitest: **114/114 passed across 16 suites (100%)**.
    - Frontend Production Build: **Built cleanly in 1.13s with 0 errors**.
    - Pyright Type Check: **0 errors, 0 warnings, 0 informations**.
    - Platform Audit: **36/36 passed (100%)**.

* **Targeted Live Data Semantics Reconciliation & Unit Precision**:
  * **Change Percent Decimal Scaling**:
    - Backend/wire sends `priceChangePercent` as a canonical decimal fraction (e.g. `0.0023` for `+0.23%`, `-0.0122` for `-1.22%`, `0.0` for `0.00%`).
    - Fixed `Change.tsx` to multiply decimal fraction by 100 for presentation (`(value * 100).toFixed(2)%`), eliminating the truncated `+0.00%` display.
  * **Zero vs Null Preservation**:
    - Fixed truthiness checks across `Change.tsx`, `market_state.py`, and `personal_dashboard.tsx` (`value == null` rather than `!value`).
    - Numeric `0` correctly renders as `0.00%`, `0`, or `0.0%` rather than falsy `—`. Missing values strictly render as `—`.
  * **Covered Warrant Spread % Calculation**:
    - Aligned `calculateSpreadPct` in `personal_dashboard.tsx` and `instrument_drawer.tsx` with canonical Formula $F-32$: $\frac{\text{Ask1} - \text{Bid1}}{\text{Bid1}} \times 100\%$.
    - Removed `!last` check that caused un-traded CWs to render `Spread % = —`.
  * **Dashboard Footer & CW Metadata Fallbacks**:
    - Corrected Dashboard footer to accurately distinguish dashboard instruments (2 CWs, 3 Stocks) from the broader Research catalog (~400+ CWs).
    - Wired contract metadata fallbacks in `PersonalDashboard` (`item.strikePrice ?? cw?.strikePrice`, etc.) so wire snapshot metadata populates dynamically.
  * **Comprehensive Regression & Acceptance Verification**:
    - Backend Pytest: **44/44 passed (100%)**.
    - Frontend Vitest: **115/115 passed across 16 suites (100%)**.
    - Frontend Production Build: **Built cleanly in 1.12s with 0 errors**.
    - Pyright Type Check: **0 errors, 0 warnings, 0 informations**.
    - Platform Audit: **36/36 passed (100%)**.

* **Targeted Realtime Subscription + Redis Runtime Correction**:
  * **CVHM2601 Root Cause & Subscription Replacement Contract**:
    - Identified root cause: `use_watchlist.ts` and `backend_websocket_client.ts` used additive `subscribeSymbols` without replacement semantics, accumulating legacy/search discovery symbols like `CVHM2601` (an unlisted/expired broker dchart symbol).
    - Implemented `syncSubscriptions(symbols)` on frontend and defaulted `replace: true` on WebSocket subscribe handler.
    - Guaranteed replacement semantics in `SubscriptionManager.set_exact_subscriptions()`.
    - Traced subscription pipeline: exactly 5 canonical symbols (`HPG`, `NVL`, `VHM`, `CVHM2615`, `CHPG2541`) sent end-to-end to FiinQuant with zero leakage.
  * **Invalid Symbol Failure Isolation & Upstream Health**:
    - Isolated stream errors in `FiinQuantProvider`: tracks `_last_error` and returns accurate `upstream_status = "ERROR"` or `"DISCONNECTED"` when streams fail, never masquerading as `LIVE`.
  * **Market Lunch-Break Semantics & Display Eligibility**:
    - Created `backend/app/market_data/market_session.py` with timezone-aware `Asia/Ho_Chi_Minh` trading session schedule:
      - Morning: `09:00 - 11:30`
      - Lunch Break: `11:30 - 13:00` (Trading paused)
      - Afternoon: `13:00 - 15:00`
    - Enforced strict distinction between `CACHE_RETENTION` (Redis preserves quotes) and `DISPLAY_ELIGIBILITY` (during lunch break, realtime trade/depth fields render `null` $\to$ `—`, while static contract terms remain visible).
  * **Real Local Redis Server Runtime Verification**:
    - Local Redis daemon running on `127.0.0.1:6379` (`PONG`).
    - Verified real Redis key `cw_research:market_state:v1:{SYMBOL}` persistence, process restart hydration, and staleness validation.
  * **Security: Bearer Token Redaction**:
    - Implemented `SensitiveDataRedactor` logging filter masking Authorization tokens (`Bearer [REDACTED]`) and credentials across all logs. Suppressed verbose `signalrcore` debug logs.
  * **Targeted Copilot Chat Persistence + History UX Pass**:
    - **Multi-Conversation History Store**: Implemented `CopilotHistoryStore` under schema version `2` with canonical key `cw_research:copilot_history:v2` supporting multiple named threads (title generated from first user query).
    - **Safe Hydration & Immediate Persistence**: Eliminated reload data loss by persisting user queries immediately upon commit and finalizing assistant messages upon stream completion with an explicit hydration barrier.
    - **Legacy V1 Migration**: Automatically migrates single-chat v1 stores (`cw_research:copilot:v1`) into the v2 conversation schema without losing existing chat history.
    - **Copilot History Navigation Panel**: Added a History button in the header immediately to the left of the Close (X) button (`[New Chat] [History] [Close]`). Clicking opens a lightweight history panel listing previous conversations ordered by `updatedAt` descending with relative timestamps (`Just now`, `2m ago`, `Yesterday`) and individual delete actions.
    - **New Chat Lifecycle**: Starting a new chat creates a fresh thread while preserving past conversations in history. Selecting an old conversation restores thread state instantly with zero redundant AI calls.
  * **Targeted Historical Data Pipeline + Local Cache Implementation**:
    - **Root Cause Resolution**: Replaced non-existent legacy mock endpoints (`/api/cw/data`, `/api/v1/history/stocks/close`) with canonical backend REST endpoint `GET /api/market/history/{symbol}` and mapped `timeframe` to FiinQuant `by` parameter (`1d`, `5m`, `30m`) preventing massive 1-minute default timeout.
    - **Empirical FiinQuant Acceptance**: Verified live retrieval of `HPG` (250 daily EOD bars in raw VND), `CVHM2615` (22 daily bars), and `CHPG2541` (199 daily bars) directly from FiinQuant `Fetch_Trading_Data`.
    - **3-Dataset Rate-Limit Friendly Strategy**:
      - `daily_1y` (by `1d`): Single annual fetch serves `1M`, `3M`, `6M`, and `1Y` views via client-side slicing without extra vendor requests.
      - `intraday_1d` (by `5m`): Serves `1D` view.
      - `intraday_5d` (by `30m`): Serves `5D` view.
    - **Versioned LocalStorage Cache (`HistoricalDataCache`)**: Namespaced under `cw_research:historical:v1:{SYMBOL}:{DATASET}` with Vietnam calendar day freshness validity, in-flight request deduplication, and max 20 symbols LRU eviction that strictly isolates and protects watchlist and Copilot storage keys.
  * **Targeted Frontend Regression Restore + Live Data Reconciliation**:
    - **Root Cause & Regression Fix**: Repaired `PersonalDashboard` partition logic and `BackendWebSocketClient` patch handling which previously polluted `warrantsMap` with stock tickers and caused `warrants.has(item.symbol)` to treat all 5 instruments as Covered Warrants.
    - **Split Dashboard Restored**: Strictly partitioned `Stocks (3)` [`HPG`, `NVL`, `VHM`] and `Covered Warrants (2)` [`CVHM2615`, `CHPG2541`] using canonical `item.instrumentType`.
    - **Fabricated 1:1 Ratios Eliminated**: Removed all default fallback `1.0` / `1:1` values in `map_snapshot.ts`, `map_instrument.ts`, and `backend_websocket_client.ts`. Missing exercise ratios and strike prices now strictly evaluate to `null` and render `—`.
  * **Phase 1 Read-Only Research Copilot Tool Layer**:
    - **Architecture Alignment**: Bridged AI market context with the canonical application layer (`MarketState`, `MarketSession`, `InstrumentRegistry`, `LiveQuantEngine`) so AI consumes the exact same data source powering the frontend WebSocket stream.
    - **Tool Registry**: Implemented bounded, read-only tools under `backend/app/ai/tools/`:
      - `get_market_status()`: Canonical session state, trading active status, upstream feed health.
      - `get_quote(symbol)`: Live canonical quote from `MarketState` in raw VND.
      - `get_order_book(symbol)`: Top-3 bid/ask depth from `MarketState` without depth fabrication.
      - `get_dashboard_snapshot()`: In-memory primary universe snapshot without issuing new FiinQuant calls.
      - `get_instrument(symbol)`: Reference contract metadata from `InstrumentRegistry`.
      - `get_quant(symbol)`: Canonical analytics delegation to `LiveQuantEngine` with structured `missing_inputs` diagnostics when terms are incomplete.
    - **Bounded Execution & Security**: Maximum 4 tool calls per turn, request-scoped caching, strict read-only whitelist (zero trading, write, filesystem, or shell capabilities).
    - **Activity Feedback**: Streamed task-specific activity labels (`Checking HPG market data…`, `Reviewing CHPG2541 analytics…`, `Checking your dashboard…`) to frontend bubble.
  * **Trading-Grade History Chart Upgrade**:
    - **TradingView Lightweight Charts Engine**: Replaced static SVG placeholder with high-performance Canvas-based `TradingChart` powered by `lightweight-charts` (v5.1.0).
    - **Full Chart Interactivity**:
      - Mouse wheel / trackpad horizontal zoom and drag pan.
      - Fit visible dataset button / double-click reset.
      - Crosshair synchronized across Price and Volume panes.
      - Interactive header readout that switches dynamically between latest candle and hovered candle OHLCV + volume + change.
    - **Separate Range and Interval**:
      - Distinct lookback Range (`1D`, `5D`, `1M`, `3M`, `6M`, `1Y`, `MAX`) and candle Interval (`1m`, `5m`, `15m`, `30m`, `1h`, `1D`, `1W`, `1M`).
      - Governed by `RANGE_INTERVAL_COMPATIBILITY` and `DEFAULT_INTERVAL_FOR_RANGE` matrices to prevent rate-limit pressure and absurd combinations.
    - **Local OHLCV Aggregation (`aggregation.ts`)**:
      - Derived weekly (`1W`) and monthly (`1M`) bars locally from canonical daily OHLCV (first open, max high, min low, last close, sum volume).
      - Derived coarser intraday bars (`15m`, `30m`, `1h`) locally from finer cached bars.
      - Zero synthetic candle fabrication when no trades exist.
    - **Realtime Current Candle Builder (`current_bar_builder.ts`)**:
      - Merges completed historical bars with live incoming ticks from `MarketQuote`.
      - Updates in-flight candle dynamically without triggering backend vendor refetches.
      - If no actual CW trade occurs, `Last` remains `null` and no fake candle is generated.
    - **Covered Warrant History Modes**:
      - `CW`: Actual CW matched trades only + volume.
      - `Underlying`: Full equity underlying price history.
      - `Both`: Synchronized dual stacked price panes (CW on top, Underlying on bottom) with shared time axis and crosshair.
      - `Relative`: Normalized performance line chart (Base 100) comparing relative move and leverage.
    - **Live CW Market Context Banner**: Displays live `Last (— if no trades)` · `Bid` · `Ask` · `Spread (Spread %)` · `Underlying Price` above chart.
    - **Technical Overlays**: P1 indicators: Reference price horizontal level for stocks, EMA 20, EMA 50, EMA 200, and intraday VWAP.

## Current State
* **Primary UI Universe**: Exactly 5 symbols `["HPG", "NVL", "VHM", "CVHM2615", "CHPG2541"]`.
* **Realtime Subscription Count**: Exactly 5 unique symbols (`["CHPG2541", "CVHM2615", "HPG", "NVL", "VHM"]`).
* **Runtime Data Mode**: `REALTIME_ONLY` (connected to FastAPI backend `/ws/market` and FiinQuant).
* **Two-Tier State Cache**: L1 `MarketState` (in-memory) + L2 `RedisMarketStateStore` (warm cache on `127.0.0.1:6379`).
* **Trading-Grade History Chart**: TradingView Canvas engine, separate Range/Interval, local aggregation, CurrentBarBuilder, dual-pane CW comparison, and normalized performance.
* **Historical Data Pipeline**: `/api/market/history/{symbol}` + 3-dataset client caching in `cw_research:historical:v1:*`.
* **Market Session**: Timezone-aware VN schedule (`Asia/Ho_Chi_Minh`) with display eligibility gating during lunch break.
* **AI Research Assistant**: Context-aware, warm persona with Phase-1 bounded read-only tool layer, multi-conversation history store (`cw_research:copilot_history:v2`), plain-text formatting, and full quantitative analytics integration.
* **Canonical WebSocket Route**: `ws://localhost:8501/ws/market`.
* **Watchlist Schema Version**: `2`.
* **Backend Pytest**: **67/67 passing (100% pass)**.
* **Frontend Vitest**: **159/159 passing across 21 suites (100% pass)**.
* **Platform Architecture Audit**: **36/36 passing (100% pass)**.
* **Pyright Type Checking**: **0 errors, 0 warnings, 0 informations**.
* **Production Build**: **0 TypeScript/bundle errors**.
* **Test Fixture Isolation**: Verified zero production imports of test fixtures or mock doubles.

## Next Steps
1. Phase 2: Connect Copilot historical data queries to canonical `HistoricalDataService` when requested.
2. Maintain strict quantitative math models and vendor integration boundaries.
