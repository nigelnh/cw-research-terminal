# Table and instrument refinement — 2026-09-02

Local worktree: `/private/tmp/cw-terminal-ux`, branch `codex/table-filter-fixes`, based on `aa51ba7`. Claude's checkout remains at `c6367a0` on `feat/ui-polish-pass`.

The original theme and layout remain. CW symbols are white and indented one monospace character; CW rows have the existing `--panel-2` background. Watchlist and trade-log panels have four outer borders. The watchlist session caption and Overview AS OF row are removed. The shared quote schema now includes LAST TRADING DATE between RATIO and DTE. It supplies both column labels and formatted STATS values, including signed price changes, yellow reference values, and real CW volume.

Drag headers to change column order; click to sort. Drag a stock to move its group, and drag a CW only among its underlying's children. Manual row order supersedes active sort/pinning. Column/row order persists locally. Keyboard equivalents: Alt + Left/Right on headers; Alt + Up/Down on rows; Enter selects a row or sorts a header. Invalid cross-group drops do nothing.

Filter dividers reach the container edges, lists scroll independently, and dates are labeled From Date / To Date. Opening the calendar preserves page/table coordinates. The instrument panel is 410px maximum instead of 460px, STATS labels/values are both 11px, and the chart shows O/H/L/C/change/V without duplicate LAST/date/close values. Candle hover includes volume, including zero.

## Real demo universe and quota

The existing backend's public `/api/market/health` reported `max_subscriptions: 33`. FiinQuant's [published pricing](https://fiinquant.vn/Pricing) assigns 33 realtime symbols to Trial; other plans have different limits. The client planner requires exactly 30 distinct subscriptions for this demo, including underlying dependencies, leaving 3 within its own 33-symbol budget. Other clients and server-pinned defaults share the backend's quota; its existing five subscriptions were not reconfigured in this review.

The demo contains HPG, FPT, VPB and nine active CWs for each stock. No VNINDEX. Exact members are in `backend/app/instruments/data/default_research_universe.json` and mirrored in the frontend identity-only defaults. Migration replaces the earlier five-symbol demo, including seeds with nonzero timestamps; custom/annotated/empty lists remain intact.

For all 27 CWs, current listed status and past first-trading date were checked against VNDIRECT's public stocks/derivatives directories. Underlying, last-trading date, maturity and ratio were cross-checked with 24HMoney. Secondary strike prices are rounded to 0.01 thousand VND; the full-precision broker values are retained, with the comparison tolerance documented. Original issue terms were not inferred. Four candidates with conflicting year-end last-trading dates were excluded. Raw source facts and URLs are retained in `backend/app/instruments/data/demo_universe_evidence_20260902.json`.

Metadata and lifecycle remain distinct; the existing conflicting instrument and quant withholding are retained. The default-universe API also rejects contracts past last-trading date, expired contracts and metadata that no longer verifies.

## Verification and local preview

239 frontend tests, 19 focused backend tests, TypeScript and the production build passed. The build retains its pre-existing large-bundle warning. Frontend unit/interaction tests cover reordered headers and matching values, synchronized STATS, parent-group movement, sibling movement and invalid cross-group drops, nested calendars, reference colors, chart hover volume/zero volume, default migration and subscription counting. Backend registry/default-universe tests include lifecycle and last-trading-date expiry. These automated tests use fixtures/mocks and do not call FiinQuant.

Browser review: 1440×900 and 1280×800 for the 30-row table and selected-instrument panel; 390×844 for filter/calendar containment. At both desktop and narrow widths, opening the calendar kept table X=21 and document horizontal scroll unchanged. Keyboard column and group movement was also exercised in the browser; native drag/drop handlers are covered by interaction tests.

The Vite app is at `http://localhost:3001/`. The temporary `/private/tmp/cw-review-api.py` on port 8502 serves this worktree's registry plus a strict allowlist of public market GET endpoints from the existing deployed backend. It forwards no credentials or mutating methods and opens no FiinQuant provider login. All 30 selected symbols returned real Traded values through the normal backend snapshot/EOD pipeline. The market is closed for a holiday, so this is last-session data, not a live-stream validation. New CW analytics and missing BID/ASK/limit quotes remain unavailable where the existing backend has no valid source. The helper is deliberately limited to the table/chart review; it does not implement authentication, AI, news, or WebSocket subscriptions.

Production deployment and integration into Claude's checkout are separate steps. No provider formulas, package dependencies, production environment settings, or production default subscriptions were changed.


## Follow-up: column alignment and detail typography

Numeric/date header labels now share the exact right edge of their values. Sort icons sit before right-aligned labels, after SYMBOL, reserve their space, and measure 1em (11.5px). The shared table/STATS names are IV_BID, BID_PRC, IV_TRD, TRD_PRC, TRD_AMT, IV_ASK, ASK_PRC and LAST_TRD_DATE. The date column sizes to its compact header (122px in the 1440px review viewport).

TRD_AMT displays the canonical provider `tradingValue` as grouped raw VND, with a session-value tooltip. It sits immediately after TRD_PRC for defaults and older saved layouts; existing custom column orders otherwise survive. Missing amounts remain a dash and zero remains zero. No last-price × volume approximation is introduced. The current last-session preview has no valid Trading_Val, so its amounts remain unavailable.

Filters show a fixed All option plus up to four scrolling options. STATS and FINANCIAL INDICATORS share 11px labels/values on a fixed 19px row pitch; shorter lists do not stretch to fill the pane. PE and PB are separate, the ROE divider and stock fundamentals footer are removed, and section headings use 12px white Rousseau Deco. The instrument kind line is 13px to match its symbol. CORPORATE EVENTS and TRADED LOGS share the same framed panel and heading treatment; the event table aligns text left and dates right, with consistent header/body padding and wrapping for longer event labels/descriptions.

Follow-up verification: 243 frontend tests pass, including actual/missing/zero turnover and saved-column insertion. TypeScript and the production build pass. Browser checks at 1440×900 and 1280×800 confirmed exact header/value edges, a five-entry filter viewport, unchanged table X=20 when opening the calendar, 19px metric rows, and no corporate-table overflow. Corporate events with long labels and descriptions were checked using an explicitly labeled, temporary local fixture; the fixture was removed afterward. The app's public-data review helper still does not serve the corporate-events endpoint. Claude's checkout remains clean and unchanged.
