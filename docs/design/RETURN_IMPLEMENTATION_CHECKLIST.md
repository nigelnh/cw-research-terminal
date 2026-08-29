# Return Handoff — implementation checklist

**For the FUTURE step**, when the approved Claude Design work comes back. Do not execute
any of this now.

---

## Before touching code

1. **Inspect the approved design.** Screens, states, the type system, the token set (if
   Claude Design produced one), the component list, and the interaction notes. Identify the
   chosen direction's rationale for **live vs last-session** — that drives the table work.
2. **Map design components → existing app components** using `COMPONENT_INVENTORY.md`. For
   each: is it KEEP-LOGIC (reskin), DECOMPOSE (split per the design), or REPLACE?
3. **Re-read `UX_DATA_CONTRACT.md`.** Every screen must still express: temporal state,
   provenance/as-of, `—` for missing, IV≠HV, quant-gate, metadata quality (quiet/explained),
   capacity. Note any place the design is silent on one of these and resolve it before
   implementing.
4. **Identify genuine frontend-architecture changes** the design requires:
   - Does the instrument detail need a **combined view-model** (unify `useDashboardData` +
     `useQuote`/`useCoveredWarrant` + `useInstrumentSpecs` so the drawer/panel shows
     last-session values — the current wiring gap)?
   - Does it need a **new backend presentation endpoint** (e.g. one instrument-detail
     payload)? Flag and design it; don't fake it client-side.
   - Does the navigation model change routing (`?tab=` / `?symbol=`)?
   - Chart: consolidate to one library (`lightweight-charts` or `chart.js`, not both).
5. **Fonts:** add the chosen faces via `@fontsource` (self-hosted, matches current
   approach) or a licensed web-font host. Verify tabular-numeral support and Vietnamese
   coverage if required. Add to `src/design/` and the CSP if a remote host is used.
6. **Design tokens:** if the design has a token set, introduce it as CSS custom properties
   in `src/design/` (extend the current `global.css` pattern) — do **not** add a CSS
   framework or CSS-in-JS runtime unless the design genuinely needs it. Migrate inline
   styles to tokens/classes incrementally, component by component.

## Implementation

7. **Incrementally, per component**, in this order (lowest-risk first): `Change` →
   `TopNav` → `PersonalDashboard` tables → `ResearchUniverse` → `InstrumentDrawer` (or its
   replacement) → `TradingChart` → `AiAssistantBubble` → auth. Keep the app shippable after
   each.
8. **Use real backend data throughout** — the deployed `/api/market/dashboard`,
   `/api/instruments`, `/api/market/history`, `/api/ai/chat`. No mocked values in the
   product path (test fixtures are fine).
9. **Preserve every state:** loading (skeletons), error (retry), empty ("no match"), `LIVE`,
   `LAST_SESSION` (with "as of" affordance), `HISTORICAL`/`STALE`, `UNAVAILABLE` (`—`),
   quant-unavailable-with-reason, `CONFLICTING`/`UNVERIFIED` metadata, capacity
   tracked/not-tracked, and the market live↔closed transition (no flicker, no stale
   overriding a fresh tick).
10. **Keep the semantic colour rule:** up=green / down=red / flat=yellow for market change.

## QA

11. **Visual comparison** against the approved Claude Design — screen by screen, state by
    state. Prepare deterministic screenshot tooling for this (Playwright) at the start of
    the implementation step, not before.
12. **Viewports:** desktop (the primary use) + whatever narrow breakpoint the design
    defines (or confirm mobile is explicitly out of scope).
13. **Accessibility:** colour contrast (esp. the market colours on the new surface),
    focus-visible on every interactive element, keyboard nav through tables and the drawer,
    `aria` labels on icon-only buttons, the AI panel's live-region behaviour, reduced-motion.
14. **Full suite:** `npx tsc --noEmit`, `npx vitest run`, `npm run build`. Update the
    universe/state assertion tests only where the *structure* legitimately changed —
    never to paper over a lost state.
15. **Backend:** `pytest` + `pyright app` if any schema/endpoint changed for the design.
16. **Deploy** (Railway backend if changed, Vercel frontend) and **verify in production**:
    dashboard populated after-hours with the "as of" affordance; Research search expands to
    the full registry; CONFLICTING warrant shows terms + withheld analytics + explanation;
    AI cites last-session closes labelled not-live; no console errors.

## Guardrails during implementation

- No change to financial formulas, the market calendar, the temporal fallback rules,
  provider ownership, subscription-capacity logic, the PostgreSQL-first history path, or
  the AI provenance/causal guardrails.
- No backend API change purely for aesthetics.
- No new heavy dependency (UI framework, design-system package, animation library) unless
  the approved design genuinely requires it and it's the smallest option.
