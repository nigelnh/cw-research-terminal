# CW Research Terminal — Design Handoff

Prepared for the visual redesign phase in **Claude Design** (claude.ai/design). This folder
is the handoff bundle: it describes **what the product is and does** so the redesign has
full context, and states **what must not change semantically** so the redesign stays
correct. The current visual language is **not** a constraint — see `DESIGN_FREEDOM.md`.

| File | Purpose |
|---|---|
| `README.md` (this) | Screen inventory, interaction flows, current stack, known structural issues |
| `UX_DATA_CONTRACT.md` | **Mandatory** data / temporal / financial / metadata semantics the design must preserve |
| `COMPONENT_INVENTORY.md` | Current components, states, data deps, redesign classification |
| `DESIGN_FREEDOM.md` | What is free to redesign vs. non-negotiable implementation constraints |
| `CLAUDE_DESIGN_PROMPT.md` | Copy-paste brief for the Claude Design web session |
| `screenshots/` | Current production UI at 6 representative states — **reference only, not the target aesthetic** |

---

## What the product is

A quantitative research terminal for **Vietnamese covered warrants** (HOSE) and their
underlying equities. Single-page React app. Audience: **recruiters evaluating the builder's
engineering + finance depth**, and **technically sophisticated users** who understand
options/warrant analytics. Not a trading platform — no orders, no positions, no P&L.

Deployed: frontend on Vercel (`cw-research-terminal.vercel.app`), FastAPI backend on
Railway, PostgreSQL + Redis. AI assistant on a free OpenRouter model.

## Current stack (frontend)

- React 18 + TypeScript + Vite. `useSyncExternalStore` for the realtime store; TanStack
  Query for server state (instrument metadata, history, dashboard fallback rows).
- **No CSS framework.** One `src/design/global.css` (~130 lines: CSS custom properties +
  ~20 utility classes). Everything else is **inline `style={{…}}`** — ~140 style objects
  across the three main components.
- Charts: `lightweight-charts` **and** `chart.js`/`react-chartjs-2` (two libraries).
- Icons: `lucide-react`. Fonts: `@fontsource/inter` + `@fontsource/jetbrains-mono`
  (bundled, self-hosted).
- Auth: Supabase magic-link (email). Anonymous use is fully supported.

## Screen inventory (major surfaces)

| # | Surface | Route | What it is |
|---|---|---|---|
| 1 | **Top navigation** | persistent | Logo, Dashboard/Research tabs, realtime capacity meter (`5 / 33 slots`), market-status word, Sign-in / account menu |
| 2 | **Dashboard** | `?tab=dashboard` | The user's tracked instruments in two tables — **Stocks** (Ref / Bid / Ask / Last / Chg / Spread / Spread% / Volume) and **Covered Warrants** (+ Underlying, Und. price, Strike, Ratio, DTE, IV bid/trade/ask). Header line states the data-state ("Market closed — showing Fri 28 Aug close"). |
| 3 | **Research** | `?tab=research` | Browse/search the instrument registry. Default: the 3 genuinely-active warrants (Symbol / Issuer / Underlying / Strike / Ratio / Maturity / DTE / Status). Typing a search expands to the whole discovered universe (~530). Row action: add to dashboard. |
| 4 | **Instrument detail drawer** | `?…&symbol=<SYM>` | Right-side slide-over. Tabs: **Overview** (Market + Contract + Volatility summary), **History** (price chart), **Quant** (IV / Greeks / Valuation & Moneyness / Model Assumptions). "Watch / Watching" toggle. For a CW being added: "Subscription Impact: consumes N slots". For a CONFLICTING warrant: a callout explaining why quant analytics are withheld while the as-issued terms still display. |
| 5 | **Research Assistant** | floating, any screen | Bottom-right launcher → chat panel. Grounded in the current instrument + market context; can call bounded read-only tools (quote, order book, contract terms, quant, history, market status). Conversation history persisted locally, multiple conversations. |
| 6 | **Sign-in dialog** | modal | Magic-link email only. Copy: "The dashboard, research and market data stay open either way." |
| — | **Loading / error / empty** | inline | Table skeletons ("Loading research universe…"), error rows ("Could not load… retry"), empty states ("No instruments match."), AI error strings, per-cell `—` for genuinely-missing data. |

## Interaction flows

**Dashboard research loop**
open terminal → glance at tracked instruments (live during a session, last-session values
outside one) → click a row → drawer opens → read Contract terms → switch to Quant tab →
read IV / Greeks / moneyness / theoretical value → optionally open History → close.

**Discover & track**
Research tab → type a symbol/underlying/issuer → results expand to the full registry →
click a row → drawer (metadata, "subscription impact") → "Watch" → it joins the dashboard
and (capacity permitting) the realtime tracked set.

**AI-assisted research**
launcher → panel → ask ("what can you tell me about CVPB2615 right now?") → assistant
reads the current instrument + market-session context, proactively pulls canonical data
(quote / terms / quant / recent EOD history), answers in plain prose grounded in that data,
never inventing numbers or causal explanations.

**Auth**
anonymous (full functionality, local watchlist) → optional Sign in → magic-link email →
personal watchlist synced server-side → Sign out → back to the local watchlist.

**Market-state transition (automatic, no user action)**
session live → realtime ticks stream in → 15:00 ICT close → rows transition to
**LAST_SESSION** values labelled "as of <date> close" (realtime-only fields like bid/ask
become `—`) → next trading session opens → realtime automatically outranks the fallback,
no refresh.

## Known structural issues worth exploring in Claude Design

These are **UX/structure** problems, not bugs. The redesign is the right place to solve
them.

1. **Generic dark-SaaS identity.** Flat dark surface, thin borders, uppercase 10px column
   heads, Inter + JetBrains Mono. Competent but indistinguishable from a template. The
   product has a strong point of view (quant rigour, provenance-first, Vietnam CW niche)
   that the visual language does not express.
2. **The instrument drawer is 890 lines** and does three jobs (market summary, contract
   reference, full quant breakdown). It is the densest, most important surface and the one
   most in need of information-hierarchy work. It also **does not yet consume the
   after-hours fallback** — its Market section shows `—` even when the dashboard row has a
   last-session value (a real wiring gap the redesign's view-model can fix).
3. **No responsive design.** `html/body` are `overflow: hidden`, layout is fixed-desktop,
   tables overflow horizontally with no adaptation. Narrow viewports are unusable.
   Whether mobile matters is a product decision for the redesign.
4. **Temporal state is a header sentence, not a first-class visual concept.** "Market
   closed — showing Fri 28 Aug close" is easy to miss; individual cells give no signal
   that a value is last-session vs live. The data layer already carries per-field
   provenance (`UX_DATA_CONTRACT.md` §2) — the design needs to *express* it.
5. **Metadata-quality signalling is inconsistent.** A muted "unverified" chip in the
   dashboard table, a loud red callout in the drawer. The design should define one
   coherent quiet-in-tables / explained-in-detail treatment.
6. **Two chart libraries** (`lightweight-charts` + `chart.js`). The redesign should pick
   one chart treatment; implementation will consolidate.
7. **AI assistant is a detached floating bubble** with no spatial relationship to the
   instrument context it uses. Its placement, and how "grounded in this instrument" is
   communicated, are open.
8. **Navigation is two tabs.** As the universe/watchlist/history surfaces grow, the
   information architecture (where search lives, how the drawer relates to the tables,
   whether History deserves its own space) is worth rethinking.

## Non-goals for the redesign

Trading/execution UI, portfolio/P&L, multi-market support, a heavy design-system
dependency, or anything that requires changing the financial semantics in
`UX_DATA_CONTRACT.md`.
