# Component Inventory

Current major frontend components, their states, data dependencies, and a redesign
classification. **This is a map, not a refactor plan** — no code is being changed in this
step. Tiny wrappers are omitted.

Classification:

- **KEEP LOGIC / REDESIGN VISUAL** — the data flow and behaviour are sound; only the
  appearance changes.
- **POSSIBLE DECOMPOSITION** — oversized or doing several jobs; the redesign is a good
  occasion to split it, but the split follows the design, not the other way round.
- **LIKELY REPLACEMENT** — the current implementation is thin/generic enough that the
  redesign will effectively rebuild it.

---

## Layout / navigation

### `TopNav` — `src/components/common/top_nav.tsx` (258 lines)
- **Purpose:** logo, Dashboard/Research tab switch, realtime capacity meter (`5 / 33 slots`
  + a thin progress bar), market-status word ("Market closed" / session name), Sign-in
  button or account menu.
- **States:** market live / closed / connecting; anonymous / signed-in; capacity
  ok / near-full.
- **Data:** `useResearchMarket` (session, feed state), `useWatchlist` (`plan.symbolCount`),
  auth session.
- **Interactions:** tab navigation (writes `?tab=`), open sign-in, open account menu.
- **Class:** KEEP LOGIC / REDESIGN VISUAL. The capacity meter and market-status indicator
  are semantically important (§6 of the data contract) — their *placement and form* are
  fully open, their *presence* is not.

### `MarketExplorer` — `src/features/market_overview/market_explorer.tsx` (181 lines)
- **Purpose:** page shell. Owns `?tab=` / `?symbol=` URL state, builds the AI context
  envelope, renders `TopNav` + (Dashboard | Research) + `AiAssistantBubble`.
- **Data:** `useResearchMarket`, `useWatchlist`, `useInstrumentSpecs`, `useDashboardData`.
- **Class:** KEEP LOGIC / REDESIGN VISUAL (it is mostly composition; the redesign's IA
  decides what it composes).

## Dashboard

### `PersonalDashboard` — `src/features/watchlist/personal_dashboard.tsx` (490 lines, ~53 inline style objects)
- **Purpose:** the user's tracked instruments in two tables — **Stocks** and **Covered
  Warrants** — plus the drawer host.
- **States:** live vs last-session (header line + per-cell `—`); empty watchlist;
  per-instrument metadata badge (`unverified`); loading.
- **Data:** `useWatchlist` (items), `useResearchMarket` (live WS quotes/warrants),
  `useDashboardData` (after-hours fallback rows + provenance), `useInstrumentSpecs`
  (canonical contract terms). Precedence: live WS quote when session active + fresh,
  otherwise the fallback row.
- **Interactions:** click row → open drawer; `×` → remove from watchlist; the CW table
  scrolls horizontally.
- **Class:** POSSIBLE DECOMPOSITION. Two near-duplicate table renderers + formatters + the
  drawer host in one file. The redesign will likely define a single "market row" concept
  with column sets per instrument type; this is where the temporal-state visual treatment
  (§2) lands.

## Research

### `ResearchUniverse` — `src/features/stock_research/research_universe.tsx` (408 lines, ~31 inline style objects)
- **Purpose:** browse/search the registry. Default view = 3 active warrants; a search
  expands to the full ~530. Columns: Symbol / Issuer / Underlying / Strike / Ratio /
  Maturity / DTE / Status.
- **States:** default (active) vs browse-all (searching/filtering); loading; error; no
  match; row is "Tracked" vs "Reference".
- **Data:** `useActiveWarrants({ status })`, `useInstrumentSpecs`, `useWatchlist`
  (`isInWatchlist` / `canAdd`), plus `useQuote` / `useCoveredWarrant` for the selected
  drawer.
- **Interactions:** search (local text filter over the fetched set), underlying/issuer
  dropdowns, click row → drawer, `+` / `✓` → add/remove from dashboard (capacity-checked,
  `alert()` on rejection — the redesign should replace the `alert`).
- **Class:** KEEP LOGIC / REDESIGN VISUAL, with POSSIBLE DECOMPOSITION of the search /
  filter bar. The default-vs-browse-all behaviour (§6) must survive.

## Instrument detail

### `InstrumentDrawer` — `src/features/warrant_info/instrument_drawer.tsx` (890 lines, ~56 inline style objects — the largest component)
- **Purpose:** right-side slide-over for one instrument. Header (symbol, type, issuer,
  underlying, Watch/Watching toggle). Tabs:
  - **Overview** — Market (Last / Change / Bid / Ask / Spread / Volume), Contract (Strike,
    Ratio, Last trading, Maturity, DTE, State, Moneyness), Volatility summary.
  - **History** — price chart (`TradingChart`) + range controls.
  - **Quant** — Implied Volatility, First-order Greeks, Valuation & Moneyness, a "Model
    Assumptions" panel (BSM / European call / independent HV / q=0).
  - Contextual banners: "Subscription Impact: consumes N slots" (when adding),
    "Conflicting contract terms" callout (CONFLICTING metadata).
- **States:** verified CW (full data) · CONFLICTING (terms shown, quant `—` + callout) ·
  PARTIAL (missing terms) · stock (no warrant fields) · not tradable / expired · loading ·
  market closed (currently shows `—` for Market — **see issue below**).
- **Data:** `deriveSelectedInstrument(...)` merges `useInstrumentSpecs` (canonical terms) +
  watchlist item (identity) + `useQuote` / `useCoveredWarrant` (live) + analytics.
- **Known gap:** the drawer **does not yet consume `useDashboardData`**, so its Market
  section shows `—` after hours even though the dashboard row for the same symbol has a
  last-session value. The redesign's view-model should unify these.
- **Class:** POSSIBLE DECOMPOSITION (strongly). This is the single most important surface
  and the densest. The redesign should drive how Overview / History / Quant relate — a
  drawer, a dedicated panel, a full page, tabs vs sections are all open.

## Charts

### `TradingChart` — `src/components/common/trading_chart.tsx` (691 lines)
- **Purpose:** historical price chart in the drawer's History tab. Range selection, EOD
  daily bars from the PostgreSQL-first history API.
- **Data:** `useHistory(...)` (TanStack Query → `/api/market/history`).
- **Class:** LIKELY REPLACEMENT. Two chart libraries are installed (`lightweight-charts`,
  `chart.js`); the redesign picks the chart treatment and implementation consolidates to
  one.

### `LiquidityDonut` — `src/components/common/liquidity_donut.tsx` (89 lines)
- **Purpose:** small order-book depth visual.
- **Class:** LIKELY REPLACEMENT (minor).

### `Change` — `src/components/common/change.tsx` (18 lines)
- **Purpose:** renders a signed % change with up/down/flat colour + arrow.
- **Class:** KEEP LOGIC / REDESIGN VISUAL. The colour semantics (§4) are fixed; the glyph
  and format are open.

## AI assistant

### `AiAssistantBubble` — `src/features/ai_assistant/ai_assistant_bubble.tsx` (627 lines)
- **Purpose:** floating launcher (bottom-right) → chat panel. Streams SSE responses,
  renders plain-text answers, shows tool-activity labels ("Checking HPG market data…"),
  manages multiple local conversations + history.
- **States:** closed / open; streaming; error (per Step 13B error taxonomy — a short
  user-facing string + an internal code logged to console); empty / with history.
- **Data:** `useAiChat` (the AI hook — endpoint from `config.apiUrl`), plus the context
  envelope from `MarketExplorer` (selected instrument, market session, `dataState`,
  `quoteAsOf`, watchlist).
- **Class:** KEEP LOGIC / REDESIGN VISUAL, with placement fully open. How the assistant
  communicates "I'm grounded in *this* instrument, as of *this* session" is an open design
  question. The SSE streaming, tool-activity labels, and error handling stay.

## Auth

### `SignInDialog` — `src/features/auth/sign_in_dialog.tsx` (145 lines)
- **Purpose:** magic-link email sign-in modal. Copy reassures that anonymous use is fine.
- **Class:** KEEP LOGIC / REDESIGN VISUAL.

### `AccountMenu` — `src/features/auth/account_menu.tsx` (137 lines)
- **Purpose:** signed-in dropdown — email, sign out.
- **Class:** KEEP LOGIC / REDESIGN VISUAL.

## Data-layer hooks (not visual, listed for context)

`useResearchMarket` / `useQuote` / `useCoveredWarrant` (the WS realtime store),
`useDashboardData` (WS + after-hours fallback merge, provenance), `useWatchlist` (local +
server watchlist), `useInstrumentSpecs` (canonical registry terms), `useActiveWarrants`
(registry browse), `useHistory` (chart data), `useAiChat` (assistant). These provide a
clean view-model surface — the redesign consumes them and should not need to understand
market-data edge cases (that is the point of Step 13C).

## Summary

| Component | Lines | Class |
|---|---|---|
| `InstrumentDrawer` | 890 | POSSIBLE DECOMPOSITION |
| `TradingChart` | 691 | LIKELY REPLACEMENT |
| `AiAssistantBubble` | 627 | KEEP LOGIC / REDESIGN VISUAL |
| `PersonalDashboard` | 490 | POSSIBLE DECOMPOSITION |
| `ResearchUniverse` | 408 | KEEP LOGIC / REDESIGN VISUAL |
| `TopNav` | 258 | KEEP LOGIC / REDESIGN VISUAL |
| `MarketExplorer` | 181 | KEEP LOGIC / REDESIGN VISUAL |
| `SignInDialog` / `AccountMenu` | 145 / 137 | KEEP LOGIC / REDESIGN VISUAL |
| `LiquidityDonut` / `Change` | 89 / 18 | LIKELY REPLACEMENT / KEEP |
