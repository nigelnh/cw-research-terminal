// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  __setReducedMotionForTests,
  DIST,
  draw,
  flip,
  introChart,
  prefersReducedMotion,
  spring,
  springTransform,
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

describe("flip", () => {
  it("returns a callable no-op for a null container", () => {
    expect(() => flip(null)()).not.toThrow();
  });

  it("returns a no-op under reduced motion", () => {
    __setReducedMotionForTests(true);
    const el = document.createElement("div");
    el.innerHTML = `<span data-symbol="A"></span><span data-symbol="B"></span>`;
    const play = flip(el);
    expect(() => play()).not.toThrow();
  });

  it("measures on capture and plays without throwing when nothing moved", () => {
    __setReducedMotionForTests(false);
    const el = document.createElement("div");
    document.body.appendChild(el);
    el.innerHTML = `<span data-symbol="A"></span><span data-symbol="B"></span>`;
    const play = flip(el);
    // reorder the DOM
    el.appendChild(el.firstElementChild!);
    expect(() => play()).not.toThrow();
    el.remove();
  });
});

describe("reduced-motion is a hard gate on every JS entry point", () => {
  it("draw / springTransform / introChart / flip all no-op and start no animation", () => {
    __setReducedMotionForTests(true);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    (path as unknown as { getTotalLength: () => number }).getTotalLength = () => 40;
    svg.appendChild(path);
    const div = document.createElement("div");
    div.appendChild(document.createElement("span")).setAttribute("data-symbol", "A");
    document.body.append(svg, div);

    expect(draw(path as unknown as SVGGeometryElement)).toBeNull();
    expect(springTransform(div, "translateY(4px)")).toBeNull();
    expect(() => introChart(svg)).not.toThrow();
    const play = flip(div);
    div.appendChild(div.firstElementChild!); // "reorder"
    expect(() => play()).not.toThrow();

    // nothing was scheduled
    expect(typeof document.getAnimations === "function" ? document.getAnimations().length : 0).toBe(0);

    svg.remove();
    div.remove();
  });
});

describe("draw", () => {
  const makePath = (len: number) => {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path") as unknown as SVGGeometryElement & {
      getTotalLength: () => number;
      animate: unknown;
    };
    path.getTotalLength = () => len;
    return path;
  };

  it("stamps the dash props then clears them on the animation's cancel/finish", () => {
    __setReducedMotionForTests(false);
    const listeners: Record<string, () => void> = {};
    const path = makePath(120);
    path.animate = () =>
      ({
        addEventListener: (ev: string, cb: () => void) => {
          listeners[ev] = cb;
        },
      }) as unknown as Animation;
    expect(draw(path)).not.toBeNull();
    expect(path.style.strokeDasharray).toBe("120");
    listeners.cancel?.();
    expect(path.style.strokeDasharray).toBe("");
  });

  it("returns null for a zero-length or non-animatable element", () => {
    __setReducedMotionForTests(false);
    expect(draw(makePath(0))).toBeNull(); // zero length
    expect(draw(makePath(50))).toBeNull(); // no .animate in this env
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
