# Design Freedom

What the Claude Design phase may change freely, and what it must not redefine.

---

## Free to redesign — no constraint from the current implementation

The current visual system is a Lovable-generated starting point. It is **not** a design
system to preserve. Everything here is open:

**Type & language**
- Font families (display + numeric + mono). The user intends to explore a **custom /
  distinctive font direction** — see `CLAUDE_DESIGN_PROMPT.md` §Typography for the
  functional requirements. Do not treat Inter / JetBrains Mono as fixed.
- Type scale, weights, tracking, casing (the uppercase 10px column heads are not sacred).
- Voice and microcopy — labels, empty states, the "Market closed" phrasing, tooltip wording
  (as long as the *meaning* in `UX_DATA_CONTRACT.md` is preserved).

**Colour & surface**
- The entire palette. The one carve-out: **up = green, down = red, flat = yellow for market
  change** is semantic, not decorative — keep those three meanings distinct and
  conventional. Everything else (background, accent, the current "Hoarfrost" `#D4E8FA`,
  borders, elevation) is open.
- Light mode / dark mode / both — the user's call. Currently dark-only.
- Surface treatment: flatness vs depth, texture, grid, dividers, card vs table.

**Layout & hierarchy**
- Dashboard composition — one combined view, split panes, cards, a dense grid, a
  spreadsheet feel — all open.
- Navigation placement and model (the two-tab bar is not fixed; search could be global,
  History could be its own space, the drawer could become a panel or a page).
- Instrument-detail placement — right drawer, left rail, modal, full page, inline
  expansion.
- AI-assistant placement — floating, docked, a panel, a sidebar, contextual to the
  selected instrument.
- Information density — the product should feel information-dense **without looking
  cluttered**; the current density is a baseline, not a target.
- Table design — column choice, grouping, sorting affordances, row height, how
  last-session vs live is expressed per cell.
- Chart presentation — style, interactions, range controls, whether depth/liquidity is
  shown and how.

**Interaction & motion**
- Micro-interactions, transitions, loading/skeleton treatment, hover/focus affordances.
- How "add to dashboard" / capacity limits are communicated (replace the current
  `alert()`).
- Responsive behaviour — including deciding whether narrow viewports / mobile are a
  supported use case at all.
- Keyboard navigation and shortcuts.

**Identity**
- A recognisable, non-generic design language. The user specifically wants to move away
  from "generic dark SaaS dashboard" / "template crypto terminal" and build something with
  a point of view suited to quantitative research.

---

## Non-negotiable — must not be redefined by the visual proposal

A design proposal **may** call for a new presentation endpoint or a new frontend view-model
later. It must **not** silently change any business semantics below.

**Data & correctness (see `UX_DATA_CONTRACT.md`)**
- The temporal state model: `LIVE` / `LAST_SESSION` / `HISTORICAL` / `DERIVED` /
  `UNAVAILABLE` and their meanings.
- As-of / provenance semantics — a last-session value must never be presented as live.
- No fabricated values to fill a table. `—` for genuinely-missing data, visibly distinct
  from zero.
- Financial field meanings — REF / LAST / BID / ASK / CHANGE / VOLUME / SPREAD / SPREAD % /
  THEO / IV / HV₂₂ / DELTA / GAMMA / THETA / VEGA / MONEYNESS / DTE / STRIKE / EXERCISE
  RATIO. In particular: **IV ≠ HV**, SPREAD % uses the canonical formula, MONEYNESS is
  backend-canonical, THEO is a model value under assumptions (not "fair value"), DELTA is
  a hedge ratio (not "probability of profit").
- The quant-availability gate — analytics appear only when the backend returns them.
- Metadata-quality states — `VERIFIED_CURRENT` / `CONFLICTING` / `PARTIAL` / `STALE` /
  `UNVERIFIED`. The design may make them quieter, but must not **hide** a material
  correctness problem (a user viewing the detail must be able to learn why analytics are
  withheld). CTCB2601's fail-closed behaviour is deliberate and stays.

**Architecture (backend — not the design's to change)**
- Financial formulas and quant conventions (Black-Scholes-Merton, q = 0, exercise-ratio
  scaling, HV₂₂ window, bounded IV solver).
- The market calendar and trading-session logic (Asia/Ho_Chi_Minh, exchange holidays,
  previous/latest/next trading session).
- The temporal fallback precedence (LIVE → last-session snapshot → EOD bars → UNAVAILABLE).
- Realtime provider ownership (single FiinQuant SignalR owner) and the ≤ 33 subscription
  capacity model. **The design must not imply every searchable instrument is
  live-subscribed.**
- PostgreSQL-first historical architecture; no browser → FiinQuant; no uncontrolled
  provider calls.
- The four distinct universe concepts (Registry ≠ Researchable ≠ Watchlist ≠ Tracked).

**AI assistant (see `docs/domain/ai_research_assistant.md`)**
- Data-provenance model and the causal-claim guardrail (no invented "why", no price
  targets, no buy/sell calls).
- The bounded read-only tool set; no unrestricted web fetch.
- The error taxonomy (short user message + internal code).

**Backend APIs**
- May not be changed purely for aesthetics. A genuine new view need (e.g. a combined
  instrument-detail payload, or the drawer consuming the dashboard resolver) is a
  legitimate implementation task for the return phase — flag it in the design, don't
  assume it away.
