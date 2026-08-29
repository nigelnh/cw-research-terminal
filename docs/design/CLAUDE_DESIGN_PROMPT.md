# Claude Design — copy-paste brief

Paste the block below into a new Claude Design (claude.ai/design) session. Attach the six
screenshots in `docs/design/screenshots/` (reference only — the current look, not the
target) and, if the session supports file context, the four docs in `docs/design/`
(`README.md`, `UX_DATA_CONTRACT.md`, `COMPONENT_INVENTORY.md`, `DESIGN_FREEDOM.md`).

---

I'm redesigning **CW Research Terminal**, a quantitative research terminal for Vietnamese
covered warrants (HOSE) and their underlying equities. It's a single-page React app. This
is a **visual and UX redesign** — the data architecture, financial logic, and backend are
built and correct; I need a new design language and information architecture on top of them.

**Audience.** Two groups: (1) recruiters evaluating my engineering + quantitative-finance
depth — the terminal is a portfolio piece; (2) technically sophisticated users who
understand options / warrant analytics. It is **not** a trading platform — no orders, no
positions, no P&L.

**The problem with the current design.** It works but it's a generic dark SaaS dashboard —
flat surface, thin borders, tiny uppercase column heads, Inter + JetBrains Mono. It could
be any fintech template. The product actually has a strong point of view — provenance-first
data, quant rigour, a specific niche (Vietnam covered warrants) — and none of that comes
through. I want something **distinctive and credible**, not another Bloomberg / Linear
clone (those can be references, not templates).

**What I want from you first: 2–4 materially different design directions** — different type
systems, colour/surface philosophies, layout models, and information hierarchies — before
we commit to one. Show them as real screens (Dashboard + instrument detail at minimum) so I
can compare. Don't pick a winner for me.

## The screens

1. **Top nav** — logo, Dashboard/Research switch, a realtime-capacity meter (e.g. "5 / 33
   slots"), a market-status indicator ("Market closed" / session name), sign-in.
2. **Dashboard** — the user's tracked instruments in two tables: **Stocks** (Ref, Bid, Ask,
   Last, Change, Spread, Spread %, Volume) and **Covered Warrants** (+ Underlying, Und.
   price, Strike, Ratio, DTE, IV bid/trade/ask). When the market is closed it shows the
   **last completed session's** values, clearly labelled "as of Fri 28 Aug close" — never
   as if live.
3. **Research** — browse/search ~530 warrant symbols. Default view shows only the few with
   verified terms; searching expands to the full registry. Row action: add to dashboard.
4. **Instrument detail** (currently a right drawer, 890 lines, the densest surface) —
   Market summary, Contract terms (Strike, Ratio, Last-trading date, Maturity, DTE,
   Moneyness), a price History chart, and a full Quant breakdown (Implied Volatility,
   first-order Greeks Δ Γ Θ ν ρ, Valuation & Moneyness, model assumptions). Some warrants
   have **conflicting metadata** — their contract terms display but quant analytics are
   deliberately withheld with an explanation. This surface most needs your
   information-hierarchy work; drawer vs panel vs full page is open.
5. **Research Assistant** — an AI chat, currently a floating bubble bottom-right. It's
   grounded in the currently-selected instrument + market session, streams responses, and
   shows what data it's looking at ("Checking HPG market data…"). How it communicates "I'm
   looking at *this* instrument, as of *this* session" and where it lives are open.
6. **Sign-in** — magic-link email only; anonymous use is fully supported.

## Interaction flows to preserve

- **Research loop:** open → scan tracked instruments → click one → read contract terms →
  read quant analytics → optionally view price history → close.
- **Discover & track:** search → find a warrant → open detail → "Watch" → it joins the
  dashboard and (capacity permitting) the live feed.
- **Market transition:** during a session, values are live; at 15:00 close they become
  last-session values labelled as such; next session, live resumes automatically. The
  design must make "live vs last-session" perceptible without the user thinking about it.

## Non-negotiable semantics (details in `UX_DATA_CONTRACT.md`)

- **A previous-session value must never look live.** Every value has a temporal state:
  `LIVE`, `LAST_SESSION`, `HISTORICAL`, `DERIVED`, `UNAVAILABLE`. The design must express
  the difference at the row level and let a user recover it at the cell level.
- **No fabricated data.** Genuinely-missing values render as `—`, visibly distinct from
  zero. Bid/ask are legitimately unavailable outside a live session.
- **Market change colour is semantic:** up = green, down = red, flat = yellow. Don't
  repurpose those three.
- **IV and HV are different quantities.** "Theoretical price" is a model value under stated
  assumptions, not "fair value". Delta is a hedge ratio, not "probability of profit".
- **Metadata quality** (`VERIFIED_CURRENT` / `CONFLICTING` / `PARTIAL` / `STALE` /
  `UNVERIFIED`) should be **quiet in dense tables** and **fully explained in the detail
  view** — but a material correctness problem must never be hidden.
- **Realtime is capacity-limited (≤ 33 symbols).** Don't imply every searchable instrument
  is permanently live.

## Typography (functional requirements — you pick the family)

- Excellent numeric readability; **tabular numerals** for all market tables.
- Clear differentiation of decimals, percentages, and +/− signs.
- Readable at dense UI sizes; a usable weight range for hierarchy.
- Web-licensable for this use; reasonable web-font performance.
- Vietnamese glyph coverage is desirable (Vietnamese UI is a possible future).

I want to explore a genuinely distinctive type direction here — including a display face
with character — not just "a clean sans".

## Free to change

Fonts, type scale, colours, surface treatment, spacing, borders/radii, iconography, table
design, chart style, dashboard composition, navigation model, instrument-detail placement,
AI-assistant placement, density, responsive behaviour, motion, and the overall visual
identity. See `DESIGN_FREEDOM.md`.

## Deliverable

2–4 distinct directions as comparable screens (Dashboard + instrument detail), each with a
short rationale — type system, colour/surface philosophy, layout model, how it handles the
live-vs-last-session distinction, and what kind of user it's for. I'll pick a direction and
we'll iterate from there.
