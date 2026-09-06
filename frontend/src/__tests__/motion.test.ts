import { afterEach, describe, expect, it } from "vitest";
import {
  __setReducedMotionForTests,
  DIST,
  prefersReducedMotion,
  spring,
  springEasing,
  SPRINGS,
  STAGGER_BASE_MS,
  STAGGER_CAP,
  staggerDelay,
} from "@/design/motion";

afterEach(() => __setReducedMotionForTests(null));

describe("prefersReducedMotion", () => {
  it("is overridable for tests and restores to the real query", () => {
    __setReducedMotionForTests(true);
    expect(prefersReducedMotion()).toBe(true);
    __setReducedMotionForTests(false);
    expect(prefersReducedMotion()).toBe(false);
    __setReducedMotionForTests(null);
    // jsdom/happy-dom matchMedia defaults to not-matching
    expect(prefersReducedMotion()).toBe(false);
  });
});

describe("springEasing", () => {
  it("produces a valid CSS linear() string that starts at 0 and lands exactly on 1", () => {
    for (const name of Object.keys(SPRINGS) as (keyof typeof SPRINGS)[]) {
      const { easing, duration } = springEasing(name);
      expect(easing.startsWith("linear(")).toBe(true);
      const stops = easing.slice(7, -1).split(",").map((s) => s.trim());
      expect(stops.length).toBeGreaterThan(4);
      expect(stops[0]).toBe("0 0%");
      expect(stops[stops.length - 1]).toBe("1 100%");
      // every stop is "<number> <number>%"
      for (const stop of stops) expect(stop).toMatch(/^-?\d+(\.\d+)? \d+(\.\d+)?%$/);
      expect(duration).toBeGreaterThan(80);
      expect(duration).toBeLessThan(1200);
    }
  });

  it("orders the tiers snap < settle < drift by settle time", () => {
    expect(springEasing("snap").duration).toBeLessThan(springEasing("settle").duration);
    expect(springEasing("settle").duration).toBeLessThan(springEasing("drift").duration);
  });

  it("only settle/drift overshoot (a stop > 1); snap never does", () => {
    const overshoots = (name: keyof typeof SPRINGS) =>
      springEasing(name).easing.slice(7, -1).split(",").some((s) => parseFloat(s) > 1.001);
    expect(overshoots("snap")).toBe(false);
    expect(overshoots("settle")).toBe(true);
  });
});

describe("spring (memoised)", () => {
  it("returns a stable reference and matches springEasing", () => {
    expect(spring("settle")).toBe(spring("settle"));
    expect(spring("snap")).toEqual(springEasing("snap"));
  });
});

describe("staggerDelay", () => {
  it("steps by the base delay and clamps at the cap", () => {
    expect(staggerDelay(0)).toBe(0);
    expect(staggerDelay(3)).toBe(3 * STAGGER_BASE_MS);
    expect(staggerDelay(STAGGER_CAP + 20)).toBe(STAGGER_CAP * STAGGER_BASE_MS);
    expect(staggerDelay(-5)).toBe(0);
  });
});

describe("DIST", () => {
  it("is an ascending nudge/step/slab scale", () => {
    expect(DIST.nudge).toBeLessThan(DIST.step);
    expect(DIST.step).toBeLessThan(DIST.slab);
  });
});
