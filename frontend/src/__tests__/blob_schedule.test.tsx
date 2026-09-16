// @vitest-environment happy-dom
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getBlobSchedulePhase,
  millisecondsUntilNextBlobPhase,
  useScheduledBlobState,
  workStateDurationMs,
} from "@/features/ai_assistant/blob_schedule";
import type { BlobVisualState } from "@/features/ai_assistant/blob_schedule";
import { PixelBlobIcon } from "@/features/ai_assistant/pixel_blob_icon";

const ict = (hour: number, minute: number, second = 0, millisecond = 0) =>
  new Date(Date.UTC(2026, 8, 17, hour - 7, minute, second, millisecond));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Blob ICT schedule", () => {
  it.each([
    [7, 59, "sleep"],
    [8, 0, "work"],
    [11, 29, "work"],
    [11, 30, "boba"],
    [11, 59, "boba"],
    [12, 0, "sleep"],
    [12, 59, "sleep"],
    [13, 0, "work"],
    [14, 59, "work"],
    [15, 0, "sleep"],
    [23, 59, "sleep"],
  ])("maps %i:%i ICT to %s", (hour, minute, phase) => {
    expect(getBlobSchedulePhase(ict(hour, minute))).toBe(phase);
  });

  it("cuts a work timer off exactly at the next fixed phase boundary", () => {
    expect(millisecondsUntilNextBlobPhase(ict(11, 29, 59, 500))).toBe(500);
    expect(millisecondsUntilNextBlobPhase(ict(14, 59, 59, 999))).toBe(1);
  });

  it("keeps coding turns strictly longer than idle turns", () => {
    const longestIdle = workStateDurationMs("idle", () => 1);
    const shortestCode = workStateDurationMs("code", () => 0);
    expect(longestIdle).toBe(30_000);
    expect(shortestCode).toBe(60_000);
    expect(shortestCode).toBeGreaterThan(longestIdle);
  });

  it("switches from work to boba at 11:30 ICT without waiting for the work pose", () => {
    vi.useFakeTimers();
    vi.setSystemTime(ict(11, 29, 59, 500));
    const states: BlobVisualState[] = [];
    const random = () => 0;
    function Probe() {
      states.push(useScheduledBlobState(random));
      return null;
    }

    render(<Probe />);
    expect(states[states.length - 1]).toBe("code");
    act(() => vi.advanceTimersByTime(500));
    expect(states[states.length - 1]).toBe("boba");
  });
});

describe("Pixel Blob state artwork", () => {
  it.each([
    ["idle", null],
    ["code", ".ai-pixel-blob-paw-left"],
    ["boba", ".ai-pixel-blob-pearl"],
    ["sleep", ".ai-pixel-blob-snot"],
  ] as const)("renders the %s variant from the supplied icon kit", (state, marker) => {
    const { container } = render(<PixelBlobIcon state={state} />);
    const svg = container.querySelector('[data-ai-blob="true"]');
    expect(svg?.getAttribute("data-ai-blob-state")).toBe(state);
    if (marker) expect(container.querySelector(marker)).not.toBeNull();
  });
});
