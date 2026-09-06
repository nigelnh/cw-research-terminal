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
  /** N/m — how hard it pulls toward rest. */
  stiffness: number;
  /** N·s/m — how fast the oscillation bleeds off. */
  damping: number;
  /** kg — inertia. */
  mass: number;
}

/**
 * The whole vocabulary. Components name a tier, never hand-write these.
 *  - `snap`   — arrives and stops, no overshoot. Input feedback: press, toggle, tab bar.
 *  - `settle` — one soft settle, a hair of overshoot. The default for live data: value
 *               rolls, row reorder, panel open.
 *  - `drift`  — slow, weighty. Large spatial moves: the instrument drawer, a view change.
 */
export const SPRINGS: Record<SpringName, SpringConfig> = {
  // snap is critically damped (ζ ≈ 1.02) so it truly never overshoots; settle and drift
  // sit under 1 for the single soft settle each is meant to have.
  snap: { stiffness: 420, damping: 42, mass: 1 },
  settle: { stiffness: 210, damping: 24, mass: 1 },
  drift: { stiffness: 120, damping: 20, mass: 1.1 },
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
 * Integrate a damped spring (from displacement 1 back to 0) and express the trajectory as
 * a CSS `linear()` easing string plus the wall-clock duration it settles in. Pure — hand
 * the result straight to `element.animate(keyframes, { duration, easing })` and the WAAP
 * animation gets the same physics as a hand-rolled rAF spring, with none of the cost.
 */
export function springEasing(name: SpringName): { easing: string; duration: number } {
  const { stiffness: k, damping: c, mass: m } = SPRINGS[name];
  const step = 1 / 60;
  const substeps = 8;
  let x = 1;
  let v = 0;
  const progress: number[] = [0];

  for (let frame = 0; frame < 180; frame++) {
    for (let i = 0; i < substeps; i++) {
      const a = (-k * x - c * v) / m;
      v += a * (step / substeps);
      x += v * (step / substeps);
    }
    progress.push(1 - x);
    if (Math.abs(x) < 5e-4 && Math.abs(v) < 5e-4) break;
  }

  if (progress.length < 3) return { easing: "linear", duration: 180 };

  const last = progress.length - 1;
  // Snap the final sample exactly to 1 so the animation lands clean.
  progress[last] = 1;
  const points = progress
    .map((p, i) => `${Number(p.toFixed(4))} ${Number(((i / last) * 100).toFixed(2))}%`)
    .join(", ");

  return { easing: `linear(${points})`, duration: Math.round(last * step * 1000) };
}

const easingCache = new Map<SpringName, { easing: string; duration: number }>();

/** `springEasing`, memoised — the three curves never change at runtime. */
export function spring(name: SpringName): { easing: string; duration: number } {
  let hit = easingCache.get(name);
  if (hit === undefined) {
    hit = springEasing(name);
    easingCache.set(name, hit);
  }
  return hit;
}

/** Delay (ms) for the i-th element of a staggered group. */
export function staggerDelay(index: number): number {
  return Math.min(Math.max(0, index), STAGGER_CAP) * STAGGER_BASE_MS;
}
