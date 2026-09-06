/**
 * Grid Terminal motion primitives — Phase 15, P1 (foundation).
 *
 * One spring vocabulary, one reduced-motion guard, no animation library. Everything here
 * is pure (no DOM) or the thinnest wrapper over the Web Animations API. See the Phase-15
 * plan: https://claude.ai/code/artifact/2cacafb3-c6d0-4b6b-a974-4520f2444846
 *
 * Springs are the source of truth. CSS-only animations use the plain `--dur-*` / `--ease-*`
 * tokens in `global.css`; anything that must interrupt cleanly on the next update (a value
 * that re-ticks mid-roll, a row dragged again mid-settle) runs through `spring()` here.
 */

export type SpringName = "snap" | "settle" | "drift";

export interface SpringConfig {
  /** Pre-baked `linear()` spring easing — progress vs. normalised time. */
  easing: string;
  /** ms the animation runs for; picked so the eye reads it as done at the end. */
  duration: number;
}

/**
 * The whole vocabulary — three pre-baked spring curves. Components name a tier, never
 * hand-write an easing. The curves are sampled critically-/near-critically-damped springs;
 * only `settle` carries a small overshoot (values past 1.0).
 *
 *  - `snap`   — arrives and stops, no overshoot. Input feedback: press, toggle, tab bar,
 *               popover, the scroll-shadow.
 *  - `settle` — one soft settle with a ~6% overshoot. The default for live data: value
 *               rolls, row reorder, panel open, quota fill.
 *  - `drift`  — slow, weighty, no overshoot. Large spatial moves: the instrument drawer,
 *               a view transition.
 */
export const SPRINGS: Record<SpringName, SpringConfig> = {
  snap: {
    duration: 190,
    easing:
      "linear(0, 0.219, 0.416, 0.577, 0.702, 0.797, 0.867, 0.918, 0.953, 0.977, 0.992, 1)",
  },
  settle: {
    duration: 300,
    easing:
      "linear(0, 0.12, 0.32, 0.548, 0.754, 0.909, 1.008, 1.058, 1.072, 1.062, 1.042, 1.02, 1.004, 0.995, 0.993, 0.995, 0.998, 1)",
  },
  drift: {
    duration: 460,
    easing:
      "linear(0, 0.09, 0.203, 0.331, 0.46, 0.579, 0.683, 0.77, 0.84, 0.895, 0.935, 0.963, 0.981, 0.992, 0.997, 1)",
  },
};

/** Per-item delay in a staggered group; the group shares the last delay past the cap. */
export const STAGGER_BASE_MS = 18;
export const STAGGER_CAP = 10;

/** Canonical travel distances (px). Nothing on a data surface should exceed `step`. */
export const DIST = { nudge: 4, step: 14, slab: 32 } as const;

let reducedOverride: boolean | null = null;

/** Test seam — pin the reduced-motion answer. Pass `null` to restore the real query. */
export function __setReducedMotionForTests(value: boolean | null): void {
  reducedOverride = value;
}

/**
 * The single source of truth for "should this move at all". Every animation entry point
 * checks it first; a `true` answer means the caller has already put the DOM in its final
 * state and nothing further should run.
 */
export function prefersReducedMotion(): boolean {
  if (reducedOverride !== null) return reducedOverride;
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * The `{ easing, duration }` for a spring tier — hand straight to
 * `element.animate(keyframes, spring("settle"))` or a CSS `transition`.
 */
export function spring(name: SpringName): SpringConfig {
  return SPRINGS[name];
}

/** Delay (ms) for the i-th element of a staggered group. */
export function staggerDelay(index: number): number {
  return Math.min(Math.max(0, index), STAGGER_CAP) * STAGGER_BASE_MS;
}

const canAnimate = (el: unknown): el is Element =>
  typeof (el as Element | null)?.animate === "function";

type ViewTransitionDocument = Document & {
  startViewTransition?: (update: () => void | Promise<void>) => { finished?: Promise<void> };
};

/**
 * Run a DOM change inside a View Transition — the outgoing and incoming states are
 * captured and animated per the `::view-transition-*` rules in global.css (a rise +
 * clip, never a cross-fade). `update` MUST apply the change synchronously (wrap React
 * state in `flushSync`). Falls back to a plain call when the API is missing or motion
 * is reduced.
 */
export function viewTransition(update: () => void): void {
  const doc = document as ViewTransitionDocument;
  if (prefersReducedMotion() || typeof doc.startViewTransition !== "function") {
    update();
    return;
  }
  doc.startViewTransition(update);
}

/**
 * FLIP. Call `flip(container)` immediately BEFORE a layout-changing update (row reorder,
 * a removal that closes a gap), then call the returned `play()` AFTER the DOM has
 * committed — wrap the React state change in `flushSync` so `play()` measures the settled
 * layout. Every element matching `selector` that changed box animates from its old
 * position to its new one with `spring.settle`, staggered in document order. Keyed by
 * `data-symbol` so rows are tracked across the reorder. No-op under reduced motion.
 */
export function flip(container: Element | null, selector = "[data-symbol]"): () => void {
  if (!container || prefersReducedMotion()) return () => {};
  const idOf = (el: Element) => el.getAttribute("data-symbol") ?? "";
  const before = new Map<string, DOMRect>();
  container.querySelectorAll(selector).forEach((el) => before.set(idOf(el), el.getBoundingClientRect()));

  return () => {
    if (prefersReducedMotion()) return;
    const { easing, duration } = spring("settle");
    let i = 0;
    container.querySelectorAll(selector).forEach((el) => {
      const b = before.get(idOf(el));
      if (!b || typeof (el as HTMLElement).animate !== "function") return;
      const a = el.getBoundingClientRect();
      const dx = b.left - a.left;
      const dy = b.top - a.top;
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) return;
      (el as HTMLElement).animate(
        [{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }],
        { duration, easing, delay: staggerDelay(i++), composite: "replace" },
      );
    });
  };
}

/**
 * Run one transform from `from` back to `to` (default rest) with a named spring. The
 * caller owns the DOM's final state; this is only the visual travel. No-op — returns
 * `null` — under reduced motion or when WAAP is unavailable.
 */
export function springTransform(
  el: Element,
  from: string,
  to = "none",
  name: SpringName = "settle",
): Animation | null {
  if (prefersReducedMotion() || !canAnimate(el)) return null;
  const { easing, duration } = spring(name);
  return el.animate([{ transform: from }, { transform: to }], { duration, easing, composite: "replace" });
}

/**
 * Draw an SVG geometry element on by sweeping its dash offset from full length to 0.
 * The element must not declare `stroke-dasharray` in CSS. Cleans the inline props on
 * finish so a later static render is unaffected. No-op under reduced motion.
 */
export function draw(el: SVGGeometryElement, name: SpringName = "snap", delay = 0): Animation | null {
  if (prefersReducedMotion() || typeof el.getTotalLength !== "function") return null;
  let length = 0;
  try {
    length = el.getTotalLength();
  } catch {
    return null; // not yet laid out
  }
  if (!length) return null;
  const { easing, duration } = spring(name);
  el.style.strokeDasharray = String(length);
  el.style.strokeDashoffset = String(length);
  const anim = el.animate([{ strokeDashoffset: length }, { strokeDashoffset: 0 }], {
    duration,
    easing,
    delay,
  });
  const clear = () => {
    el.style.strokeDasharray = "";
    el.style.strokeDashoffset = "";
  };
  anim.addEventListener("finish", clear);
  anim.addEventListener("cancel", clear);
  return anim;
}

/**
 * Chart intro: draw the line(s) on and grow the bars up from the baseline. Call from a
 * `useLayoutEffect` keyed on the *session*, not on every data poll — a live market that
 * re-drew its charts every 15s would be pure noise. No-op under reduced motion.
 *
 * `.overview-spark-grid` (the hour ticks) and `<line>` (the reference) are skipped —
 * scaffolding is there from the first frame, only data arrives.
 */
export function introChart(root: Element | null | undefined): void {
  if (!root || prefersReducedMotion()) return;
  const { easing, duration } = spring("drift");

  root
    .querySelectorAll<SVGGeometryElement>("polyline, path:not(.overview-spark-grid)")
    .forEach((el) => draw(el, "drift"));

  const rects = [...root.querySelectorAll<SVGRectElement>("rect")];
  rects.forEach((el, i) => {
    if (typeof el.animate !== "function") return;
    el.style.transformBox = "fill-box";
    el.style.transformOrigin = "bottom";
    el.animate([{ transform: "scaleY(0)" }, { transform: "scaleY(1)" }], {
      duration,
      easing,
      delay: staggerDelay(Math.floor((i / Math.max(1, rects.length)) * (STAGGER_CAP + 1))),
    });
  });
}
