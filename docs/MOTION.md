# Grid Terminal Motion

Reference for the motion system (Phase 15, PRs #49–#55). Plan / rationale:
<https://claude.ai/code/artifact/2cacafb3-c6d0-4b6b-a974-4520f2444846>.

**The one rule:** motion earns its place by *explaining a change* — an open, a move, a
new value, a load completing. If nothing changed, nothing moves. No cross-fades: things
move from where they were, they don't dissolve.

Everything lives in `frontend/src/design/motion.ts` (JS) and a token block in
`global.css`. No animation library.

---

## Springs

Three pre-baked `linear()` curves + fixed durations. Components name a tier; nobody
hand-writes an easing.

| tier | duration | shape | use |
|---|---|---|---|
| `snap` | 190 ms | no overshoot | input feedback: press, toggle, tab bar, popover, scroll-shadow, breadth-triangle pop |
| `settle` | 300 ms | ~6 % overshoot | the default for live data: value roll, row reorder (FLIP), panel/drawer open, quota fill, news-row entry |
| `drift` | 460 ms | no overshoot, weighty | large spatial moves: the instrument drawer |

```ts
import { spring } from "@/design/motion";

el.animate([{ transform: "translateY(8px)" }, { transform: "none" }], spring("settle"));
// spring(name) -> { easing: "linear(…)", duration: number }
```

CSS-only, non-interruptible animations use the plain tokens instead — spring physics
stays in JS:

```
--dur-snap: 140ms;  --dur-settle: 240ms;  --dur-drift: 420ms;
--ease-out: cubic-bezier(0.2, 0, 0, 1);   --ease-in: cubic-bezier(0.5, 0, 1, 1);
--stagger: 18ms;    --flash-decay: 620ms;
```

---

## Reduced motion

`prefersReducedMotion()` is the single gate. **Every JS entry point checks it first** and
returns without scheduling anything; the caller has already put the DOM in its final
state. Every CSS animation/transition is inside a matching
`@media (prefers-reduced-motion: reduce)` override.

`__setReducedMotionForTests(true | false | null)` pins the answer in tests — use it in
files that assert DOM shape around an animated element (e.g. the now-async popover close).

---

## Helpers (`motion.ts`)

| function | what it does |
|---|---|
| `spring(name)` | `{ easing, duration }` for a tier |
| `flip(container, selector?)` | measure boxes → returns `play()`; call `play()` after a `flushSync`'d layout change and every moved `[data-symbol]` element travels from its old box to its new one, staggered |
| `draw(el, name?, delay?)` | sweep an SVG geometry element's `stroke-dashoffset` full→0; clears the dash props on finish/cancel |
| `introChart(root)` | draw every line in `root` on + grow every `<rect>` from its baseline; call from a `useLayoutEffect` keyed on the **session**, never a data poll |
| `springTransform(el, from, to?, name?)` | one transform back to rest with a spring |
| `viewTransition(update)` | run `update()` inside `document.startViewTransition` (falls back to a plain call); `update` must apply the DOM change synchronously — wrap React state in `flushSync` |
| `staggerDelay(i)` | `min(i, 10) * 18ms` |
| `DIST` | `{ nudge: 4, step: 14, slab: 32 }` px — canonical travel; nothing on a data surface exceeds `step` |

FLIP pattern:

```tsx
const play = flip(tbodyRef.current);
flushSync(() => setRows(next));   // commit the reorder
play();                           // measure "after", animate the inverse
```

---

## What's animated, and how

| surface | mechanism | file |
|---|---|---|
| sticky table header shadow | `animation-timeline: scroll()` on a `::after`, opacity only | `global.css` |
| index-card headline value | `RollingNumber` — old value clips out, new springs in (`settle`), short wake behind; retargets on a mid-roll re-tick | `realtime_value.tsx` |
| realtime value flash | `--flash-decay` 620 ms, `--ease-out` | `realtime_value.tsx` / `global.css` |
| sparkline + volume bars | `introChart()` on mount / session rollover | `market_overview_strip.tsx` |
| quota bar fill | `spring("settle")` easing on the `width` transition + one pulse crossing into amber | `ai_anchor.tsx` |
| tab switch | View Transition; only `.page-shell` is named, so the header / drawer / anchor hold still | `market_explorer.tsx` / `global.css` |
| instrument drawer | slide up from below on first open (`drift`) | `instrument_panel.tsx` |
| filter / news popover | clip open from the trigger (`snap`); clip back out on close, then unmount | `filter_popover.tsx` / `global.css` |
| watchlist / registry reorder + dismiss | `flip()` | `personal_dashboard.tsx` / `research_table.tsx` |
| row selection rail | 3 px `::before`, `scaleX(0)→1` | `global.css` |
| Orbit anchor | mark turns while a request is in flight, still otherwise | `ai_anchor.tsx` / `global.css` |
| filter caret | rotates 180° on open | `filter_popover.tsx` / `global.css` |
| research-trace steps | wipe in from the left as they start (live trace only) | `ai_anchor.tsx` / `global.css` |
| research-trace body | `0fr↔1fr` grid-row height collapse when the answer lands | `ai_anchor.tsx` / `global.css` |
| breadth triangles (▲▼) | spring-scale on a count change | `market_overview_strip.tsx` |
| news-feed rows | new rows wipe down from the top (first paint skipped) | `news_feed.tsx` / `global.css` |

---

## Guardrails

- **Transform / opacity / clip-path / stroke-dashoffset only** for anything that can run
  during a burst of updates. Two deliberate exceptions, both one-shot and low-frequency:
  the quota bar's `width` transition and the trace body's `grid-template-rows` collapse.
- **60 fps floor.** A dropped frame on a trading screen reads as a data glitch. The dense
  watchlist table stays **flash-only** — no per-cell roll (forty cells springing at once
  is noise, and it's the hot path).
- **Interruption, not queueing.** A value that updates mid-animation retargets to the
  newest value — that's why springs, not tweens. Covered by
  `realtime_feedback.test.tsx` ("retargets on a mid-roll re-tick").
- **The reduced-motion path is written in the same commit** as the animation, and
  `motion.test.ts` asserts every JS entry point no-ops under it.

## Not done / dropped

Custom-SVG pin/hide state-pair morphs (need drawn geometry, low payoff); a first-load
stagger (replays on every open — reads as noise); hidden-row self-collapse (the FLIP
gap-close already carries it); an AI-answer settle (too subtle). A CI perf-budget
assertion under a simulated tick burst was scoped but is impractical in the current test
env — the "no layout-prop animation" convention above is the standing guard instead.
