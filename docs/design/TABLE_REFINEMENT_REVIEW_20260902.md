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
