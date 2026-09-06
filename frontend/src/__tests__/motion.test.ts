// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  __setReducedMotionForTests,
  DIST,
  prefersReducedMotion,
  spring,
  SPRINGS,
  STAGGER_BASE_MS,
  STAGGER_CAP,
  staggerDelay,
  viewTransition,
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

describe("SPRINGS", () => {
  const values = (easing: string) =>
    easing
      .slice(easing.indexOf("(") + 1, -1)
      .split(",")
      .map((s) => parseFloat(s.trim()));

  it("every tier is a well-formed linear() curve from 0 to exactly 1", () => {
    for (const name of Object.keys(SPRINGS) as (keyof typeof SPRINGS)[]) {
      const { easing, duration } = spring(name);
      expect(easing.startsWith("linear(")).toBe(true);
      const v = values(easing);
      expect(v.length).toBeGreaterThan(6);
      expect(v[0]).toBe(0);
      expect(v[v.length - 1]).toBe(1);
      expect(duration).toBeGreaterThan(120);
      expect(duration).toBeLessThan(600);
    }
  });

  it("orders the tiers snap < settle < drift by duration", () => {
    expect(spring("snap").duration).toBeLessThan(spring("settle").duration);
    expect(spring("settle").duration).toBeLessThan(spring("drift").duration);
  });

  it("only settle overshoots (a control point past 1); snap and drift never do", () => {
    const overshoots = (name: keyof typeof SPRINGS) => values(spring(name).easing).some((n) => n > 1.001);
    expect(overshoots("snap")).toBe(false);
    expect(overshoots("drift")).toBe(false);
    expect(overshoots("settle")).toBe(true);
  });

  it("spring() hands back the same object each call", () => {
    expect(spring("settle")).toBe(SPRINGS.settle);
    expect(spring("drift")).toBe(spring("drift"));
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

describe("viewTransition", () => {
  const doc = document as unknown as { startViewTransition?: unknown };

  afterEach(() => {
    delete doc.startViewTransition;
  });

  it("runs the update directly when the API is absent", () => {
    const update = vi.fn();
    viewTransition(update);
    expect(update).toHaveBeenCalledTimes(1);
  });

  it("routes through startViewTransition when it exists and motion is allowed", () => {
    const start = vi.fn((cb: () => void) => {
      cb();
      return { finished: Promise.resolve() };
    });
    doc.startViewTransition = start;
    const update = vi.fn();
    viewTransition(update);
    expect(start).toHaveBeenCalledTimes(1);
    expect(update).toHaveBeenCalledTimes(1);
  });

  it("bypasses the API entirely under reduced motion", () => {
    __setReducedMotionForTests(true);
    const start = vi.fn();
    doc.startViewTransition = start;
    const update = vi.fn();
    viewTransition(update);
    expect(start).not.toHaveBeenCalled();
    expect(update).toHaveBeenCalledTimes(1);
  });
});
