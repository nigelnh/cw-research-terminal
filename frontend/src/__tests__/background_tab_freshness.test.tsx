// @vitest-environment happy-dom
/**
 * Background-tab behaviour. A hidden document freezes CSS animations and clamps timers,
 * and React Query suspends `refetchInterval` for it — so switching away froze every
 * REST-served row, coming back did not refresh them (this app disables refetch-on-focus
 * globally), and the whole board replayed a burst of long-dead flashes.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { RealtimeValue, REALTIME_FLASH_DURATION_MS } from "@/components/common/realtime_value";

afterEach(() => {
  cleanup();
  setVisibility("visible");
});

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
  document.dispatchEvent(new Event("visibilitychange"));
}

const flashing = (el: Element | null) => (el as HTMLElement).className.includes("realtime-flash");

describe("flash pulses do not replay after a spell in the background", () => {
  it("drops a pulse that aged out while the tab was hidden", () => {
    // A pulse that started long enough ago to be over, but whose expiry timer never ran.
    const stale = { sequence: 1, direction: "up" as const, startedAt: Date.now() - 60_000 };
    const { container } = render(<RealtimeValue pulse={stale}>1</RealtimeValue>);
    expect(flashing(container.firstElementChild)).toBe(false);
  });

  it("re-evaluates on the way back so a frozen flash is cleared, not resumed", () => {
    vi.useFakeTimers();
    try {
      const pulse = { sequence: 1, direction: "up" as const, startedAt: Date.now() };
      const { container } = render(<RealtimeValue pulse={pulse}>1</RealtimeValue>);
      expect(flashing(container.firstElementChild)).toBe(true);

      // Away for a while: wall-clock advances but the throttled expiry timer never fires.
      setVisibility("hidden");
      vi.setSystemTime(Date.now() + 60_000);
      act(() => { setVisibility("visible"); });

      expect(flashing(container.firstElementChild)).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a genuinely fresh pulse still flashes after returning", () => {
    setVisibility("hidden");
    act(() => { setVisibility("visible"); });
    const fresh = { sequence: 2, direction: "down" as const, startedAt: Date.now() };
    const { container } = render(<RealtimeValue pulse={fresh}>1</RealtimeValue>);
    expect(flashing(container.firstElementChild)).toBe(true);
    expect(Date.now() - fresh.startedAt).toBeLessThan(REALTIME_FLASH_DURATION_MS);
  });
});

describe("market polling stays alive in a background tab", () => {
  it("the dashboard and overview queries opt out of the hidden-tab suspension", async () => {
    // Read the source rather than mounting the whole data layer: the defect was a missing
    // option, and its presence is exactly what has to be pinned.
    const files = import.meta.glob("../data/query/{use_dashboard_data,use_market_overview}.ts", {
      query: "?raw",
      import: "default",
      eager: true,
    }) as Record<string, string>;

    const entries = Object.entries(files);
    expect(entries.length).toBe(2);
    for (const [path, source] of entries) {
      expect(source, `${path} must keep polling while hidden`).toContain(
        "refetchIntervalInBackground: true",
      );
      expect(source, `${path} must repaint on focus`).toContain("refetchOnWindowFocus: true");
    }
  });
});
