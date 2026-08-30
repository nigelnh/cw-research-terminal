# Grid Terminal — data follow-ups

The "Direction C — Grid Terminal" redesign is implemented and wired to real backend data
wherever a field exists. This is the list of surfaces that render `—` / a "pending" note
today because there is **no backend field yet** — deliberately not faked. Each needs a
backend/provider change before the UI can light up.

| Surface | Where | What it needs |
|---|---|---|
| **Foreign flow** — `FRN BUY` / `FRN SELL` / `FRN ROOM` | Watchlist → Stocks table | `foreignBuy` / `foreignSell` / `foreignRoom` on the quote wire + populate `map_snapshot.ts` / `map_patch.ts` (the `MarketQuote` fields already exist, the mappers just don't set them). |
| **Index-strip breadth** — `VOL(MIL)` / `VAL(BIL)` / gainers-flat-losers | `MarketOverviewStrip` (both tabs) | Per-index aggregate volume, traded value, and advance/decline counts. No current source. |
| **Non-VNINDEX index quotes** — VN30 / HNX30 / HNXINDEX / VNXALL / HNXUPCOM | `MarketOverviewStrip` | Only `VNINDEX` is in the subscribed realtime set. Either subscribe these indices (costs capacity) or add a lightweight REST index-snapshot endpoint. |
| **Index-card sparklines** | `MarketOverviewStrip` cards (hatched placeholder + `1D`) | A short intraday or daily series per index. |
| **Stock / index fundamentals** — EPS, PE, PB, ROE, ROA, ROIC, gross margin, net margin | Instrument panel → QUANT tab (stock/index) | A fundamentals provider/endpoint. All rows render `—`. |
| **Corporate events** — cash/stock dividends, rights issues, ex-div / issue dates | Instrument panel → QUANT tab (stock/index), `CORP EVENTS` table | A corp-actions feed. Table renders an empty state. |
| **Live Time & Sales** | Instrument panel → QUANT tab (CW), during a live session | A trade-print feed. Shown as a "not yet wired" note even when the session is active. |
| **Price Depth / Market Depth panels** | Instrument panel → QUANT tab (CW), during a live session | Full L2 book. The existing `LiquidityDonut` covers only a summary; the two depth panes are placeholders. |
| **AI attachment upload** | REPL bar `@` button | Multipart support in `/api/ai/chat`. The file picker works and shows a chip, but the chip is labelled "not yet sent". |

## Non-data follow-ups

- **Chart library consolidation** — the app still ships both `lightweight-charts` (used) and
  `chart.js` / `react-chartjs-2` (now unused by the panel). Drop `chart.js` once nothing
  else references it to cut ~200 kB from the bundle.
- **`AccountMenu`** (`src/features/auth/account_menu.tsx`) is now superseded by the header's
  inline sign-in control and is no longer mounted; delete once no test imports it.
