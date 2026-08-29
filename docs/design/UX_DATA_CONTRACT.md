# UX Data & Semantics Contract

**Mandatory.** The visual redesign has full freedom over *how* these are shown, but the
*meanings* below were established in Steps 13A–13C and are load-bearing. A design that
reinterprets them is wrong even if it looks better. When in doubt, the rule is: **never let
the presentation imply something the data does not support.**

---

## 1. The core principle

> Do **not** show "missing" when the system has a trustworthy fallback.
> Do **not** fabricate a value to make a table look complete.
> A previous-session value must **never** be labelled or styled as live.

Every cell is one of: a real live value, a real last-session value (labelled as such), a
real historical value, a value derived from other real values, or genuinely unavailable
(`—`). There is no sixth option.

## 2. Data temporal states

Every value the UI renders carries exactly one temporal origin. The backend supplies this
per field-group on each dashboard row as `provenance.{quote|book|analytics}` =
`{ state, source, asOf, sessionDate, stale }`, plus a row-level `displayState`.

| State | Meaning | Example |
|---|---|---|
| `LIVE` | Fresh tick during an active HOSE session. The only state that may look "live". | mid-session last price |
| `LAST_SESSION` | Final / most-recent value from the **last completed trading session**. Legitimate, but **not current**. | Saturday, showing Friday's close |
| `HISTORICAL` | A persisted daily bar **older** than the last completed session (e.g. a warrant that last traded two sessions ago). | last trade 3 days back |
| `DERIVED` | Computed from other stated values, not observed. | change % = (close − prior close) / prior close |
| `UNAVAILABLE` | Realtime-only field with no legitimate fallback. Render `—`, never `0`, never a guess. | bid/ask outside a live session with no closing snapshot |

Row-level `displayState`: `LIVE` | `LAST_SESSION` | `MIXED` (some groups live, some not) |
`UNAVAILABLE`.

**Design requirement:** the difference between `LIVE` and `LAST_SESSION` must be
perceptible at the row/screen level *and* recoverable at the cell level (e.g. the user can
tell that *this specific number* is Friday's close, not now). Today it is a single header
sentence — that is the minimum bar, not a ceiling.

## 3. As-of / provenance semantics

Each value can answer: **what** is it, **which session** is it from, **when** was it
observed, **is it live or previous-session**, **why** is it unavailable.

```
value:        22100        (already in canonical units — raw VND here)
source:       EOD_BARS     (LIVE_FEED | SNAPSHOT_FINAL | SNAPSHOT_CHECKPOINT | EOD_BARS | PRIOR_CLOSE | QUANT_LIVE | QUANT_EOD | NONE)
asOf:         2026-08-28T15:00:00+07:00
sessionDate:  2026-08-28
state:        LAST_SESSION
stale:        false
```

`22,100 VND — as of Fri 28 Aug close` must **never** read as a live quote when the market
is closed. The exact visual (a badge, a tint, a timestamp column, an icon, muted styling)
is the designer's call; the semantic distinction is not optional.

Row-level meta from the endpoint: `market_session`, `market_session_active`,
`latest_completed_session`, `calendar_confidence` (`AUTHORITATIVE` | `APPROXIMATE` — the
trading-holiday calendar is estimated beyond the confirmed horizon; only surface this if
the user is reasoning about future dates).

## 4. Financial semantics

Just enough for a designer to avoid presenting these incorrectly.

| Field | Meaning | Design note |
|---|---|---|
| **REF** | Reference price = the previous session's close (HOSE convention). The basis for CHANGE. | not "yesterday" — previous *trading* session |
| **LAST** | Last matched trade price. `null` during an open session = no trade yet today; a real value outside a session = that session's close. | |
| **BID / ASK** | Best buy / sell order price. **Legitimately unavailable outside a live session** unless a closing snapshot was captured — FiinQuant has no historical order book. | `—` here is correct, not a failure |
| **CHANGE / CHANGE %** | vs REF. Positive = green, negative = red, flat = yellow — **colour carries meaning, do not repurpose it.** | |
| **VOLUME** | Cumulative matched volume for the session. | |
| **SPREAD** | ASK − BID, absolute. Only exists when both BID and ASK exist. | never compute from OHLC |
| **SPREAD %** | `100 × (ASK − BID) / MID` — the canonical convention from Step 13A. Backend-supplied; **do not recompute a different formula.** | |
| **UNDERLYING PRICE** | Spot price of the equity the warrant is written on. | |
| **STRIKE** | The price at which the warrant can be exercised (raw VND). | |
| **EXERCISE RATIO** | Warrants per 1 underlying share, e.g. `2:1`. Effective (corporate-action-adjusted) where known. | |
| **DTE** | Days to expiry / maturity. Canonical calendar-day count to the maturity date, VN calendar. | anchored to the VN date, not the viewer's clock |
| **MONEYNESS (S/K)** | Underlying spot ÷ strike. Backend-canonical single value + an ITM/ATM/OTM label. **Never recompute** from raw prices. | |
| **IV bid / trade / ask** | Implied volatility — the volatility the *market price* implies, back-solved from BID / LAST / ASK. Decimal (0.32 = 32%). | |
| **HV₂₂** | Historical (realised) volatility over 22 trading sessions. **A different quantity from IV** — computed from past returns, not prices. Never equate or merge them. | label distinctly |
| **THEO / Theoretical Fair Price** | Model value under an *independent* volatility assumption (HV). Black-Scholes-Merton, European call, dividend-protected (q = 0). It is a *model value under stated assumptions* — **not "the fair value" / "what it's worth".** | phrasing matters |
| **DELTA (Δ)** | ∂(warrant price)/∂(underlying price) × exercise-ratio scaling. A hedge ratio / local sensitivity — **only loosely** the probability of finishing in-the-money. Do not label it "probability of profit". | |
| **GAMMA (Γ)** | ∂Δ/∂(underlying). | |
| **THETA (Θ)** | Time decay per day. Keep the "/ day" unit. | |
| **VEGA (ν)** | Sensitivity per +1 percentage point of volatility. Keep the "/ 1%" unit. | |
| **RHO (ρ)** | Sensitivity per +1 percentage point of the risk-free rate. | |

**Quant availability gate:** IV / Greeks / moneyness / theoretical price are shown **only**
when the backend's quant engine returns them. They require verified contract terms **and** a
usable underlying spot. When unavailable the reason is one of: metadata not verified,
metadata conflicting, contract not tradable (past last-trading-day), or an input missing
for that session. The design must be able to show "analytics unavailable — <short reason>"
without it looking like an error state.

## 5. Metadata-quality states

The registry grades every instrument's contract metadata:

| State | Meaning | Consequence |
|---|---|---|
| `VERIFIED_CURRENT` | Terms confirmed against an auditable source, fresh. | full analytics |
| `CONFLICTING` | Terms are known but disagree across public sources (e.g. an unresolved corporate-action adjustment). | as-issued terms **display**; quant analytics **withheld** |
| `PARTIAL` | Some terms missing (strike / ratio / maturity). | analytics unavailable |
| `STALE` | Was verified, now past the freshness window. | treated as unverified |
| `UNVERIFIED` | Discovered but never confirmed. | identity only |

Separately, `dataQuality` = `COMPLETE | PARTIAL`, and `quantAvailable` = boolean.

**Design direction (from the brief, not a mandate):** the dense tables want a **quiet**
indication (a small muted marker, a subtle row treatment) — not a loud red badge per row.
The **detail drawer** carries the full explanation and provenance. **But the design must
not hide a material correctness problem** — a user looking at the detail must be able to
learn *why* analytics are missing.

**Worked example — CTCB2601:** issuer ACBS, underlying TCB, strike 37,000, ratio 4:1,
maturity 2026-10-26 — all shown. Metadata state `CONFLICTING` → IV, Greeks, moneyness,
theoretical price all `—`, with a drawer callout: *"Conflicting contract terms: the
as-issued terms are known, but an effective (corporate-action-adjusted) value disagrees
across public sources. Quant analytics are held back until reconciled."* This behaviour is
**deliberate engineering evidence** and must survive the redesign.

## 6. Research-universe architecture

Four **distinct** concepts. A design that conflates them is wrong.

| Concept | What it is | Size |
|---|---|---|
| **Instrument Registry** | Every warrant symbol the project has discovered. | ~530 |
| **Researchable universe** | The registry, browsable by search. Contract terms exist only where genuinely known (~3 fully verified today). | ~530 (search), 3 (default view) |
| **User watchlist** | The user's chosen instruments — identity + preference, persisted (local when anonymous, server when signed in). Does **not** store contract terms. | user's choice |
| **Realtime tracked set** | Symbols with a live subscription. Capacity-limited (currently 33 slots). The union of connected users' dashboards. | ≤ 33 |

**The design must not imply "everything visible in search is permanently live-subscribed."**
Static metadata and history are available for any registry symbol on demand; realtime is
the scarce resource. The current UI shows this as a `5 / 33 slots` meter and a
"Subscription Impact: consumes N slots" line in the drawer — the redesign can express
capacity differently, but the *concept* stays.

## 7. States the redesign must be able to render

- `LIVE` value (during a session)
- `LAST_SESSION` value with an "as of <date> close" affordance
- `HISTORICAL` / `STALE` value
- `UNAVAILABLE` (`—`) — visibly distinct from zero
- Quant-analytics-unavailable with a short reason
- `CONFLICTING` / `UNVERIFIED` metadata — quiet in tables, explained in detail
- Realtime capacity: tracked vs not-tracked, slots remaining
- Loading, error, and empty states for every table and the chart
- The AI assistant's "grounded in <this instrument> as of <this session>" context
