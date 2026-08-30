# Grid Terminal — data follow-ups

The "Direction C — Grid Terminal" redesign is implemented and wired to real backend data
wherever a field exists. This is the list of surfaces that render `—` / a "pending" note
today because there is **no backend field yet** — deliberately not faked. Each needs a
backend/provider change before the UI can light up.

| Surface | Where | What it needs |
|---|---|---|
| **Foreign flow** — `FRN BUY` / `FRN SELL` / `FRN ROOM` | Watchlist → Stocks table | `foreignBuy` / `foreignSell` / `foreignRoom` on the quote wire + populate `map_snapshot.ts` / `map_patch.ts` (the `MarketQuote` fields already exist, the mappers just don't set them). |
| **Stock / index fundamentals** — EPS, PE, PB, ROE, ROA, ROIC, gross margin, net margin, and the quarterly revenue/profit bar chart | Instrument panel → QUANT tab (stock/index) | A fundamentals / financial-statement provider. All rows render `—`; the left chart slot is a labelled placeholder. |
| **Corporate events** — cash/stock dividends, rights issues, ex-div / issue dates | Instrument panel → QUANT tab (stock/index), `CORP EVENTS` table | A corp-actions feed. Table renders an empty state. |
| **Live Time & Sales** — `TIME \| TRD \| +/- \| CHG% \| VOL \| B/S` | Instrument panel → OVERVIEW tab (all non-index instruments) | A trade-print feed. Session-gated honest empty state. The v3 design replaced the OVERVIEW price-history mini-table with this panel; historical price context is now carried by the chart alone. |
| **Price Depth / Market Depth panels** | Instrument panel → QUANT tab (CW), during a live session | Full L2 book. The existing `LiquidityDonut` covers only a summary; the two depth panes are placeholders. |
| **AI attachment upload** | REPL bar `@` button | Multipart support in `/api/ai/chat`. The file picker works and shows a chip, but the chip is labelled "not yet sent". |

## Non-data follow-ups

- **Chart library consolidation** — the app still ships both `lightweight-charts` (used) and
  `chart.js` / `react-chartjs-2` (now unused by the panel). Drop `chart.js` once nothing
  else references it to cut ~200 kB from the bundle.
- **`AccountMenu`** (`src/features/auth/account_menu.tsx`) is now superseded by the header's
  inline sign-in control and is no longer mounted; delete once no test imports it.
