// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { RealtimeValue } from "@/components/common/realtime_value";
import { priceTone, MARKET_COLOR } from "@/components/common/grid_table";
import { quoteCell } from "@/components/common/quote_columns";

const pulse = { sequence: 1, direction: "up" as const, startedAt: Date.now() };

/** A row sitting at whatever `last` says, inside a 20–30 band with ref 25. */
function row(last: number | null, extra: Record<string, unknown> = {}) {
  return {
    symbol: "HPG", ref: 25, ceiling: 30, floor: 20,
    bid: null, ask: null, last, chgPct: null, vol: null,
    strike: null, ratio: null, ivBid: null, ivTrade: null, ivAsk: null,
    lastTradingDate: null, dteText: "—",
    ...extra,
  } as never;
}

describe("priceTone — one band decision behind both the colour and the flash", () => {
  it("names the band the price sits in", () => {
    expect(priceTone(30, { ref: 25, ceiling: 30, floor: 20 })).toBe("ceiling");
    expect(priceTone(20, { ref: 25, ceiling: 30, floor: 20 })).toBe("floor");
    expect(priceTone(27, { ref: 25, ceiling: 30, floor: 20 })).toBe("up");
    expect(priceTone(23, { ref: 25, ceiling: 30, floor: 20 })).toBe("down");
    expect(priceTone(25, { ref: 25, ceiling: 30, floor: 20 })).toBe("flat");
    expect(priceTone(null, { ref: 25 })).toBe("null");
  });

  it("stays in lockstep with the colour the digits use", () => {
    for (const v of [30, 20, 27, 23, 25, null]) {
      const r = { ref: 25, ceiling: 30, floor: 20 };
      expect(MARKET_COLOR[priceTone(v, r)]).toBe(quoteCell(row(v), "last").color);
    }
  });
});

describe("RealtimeValue — the wash matches the band, not just the direction", () => {
  const toneClass = (tone: Parameters<typeof RealtimeValue>[0]["tone"]) => {
    const { container } = render(
      <RealtimeValue pulse={pulse} tone={tone}>1</RealtimeValue>,
    );
    return (container.firstElementChild as HTMLElement).className;
  };

  it("an up tick that lands on the ceiling flashes ceiling, not green", () => {
    expect(toneClass("ceiling")).toContain("realtime-flash-ceiling");
    expect(toneClass("ceiling")).not.toContain("realtime-flash-up");
  });

  it("flashes floor and flat for their own bands", () => {
    expect(toneClass("floor")).toContain("realtime-flash-floor");
    expect(toneClass("flat")).toContain("realtime-flash-flat");
  });

  it("falls back to the pulse direction with no tone, or an unusable one", () => {
    expect(toneClass(undefined)).toContain("realtime-flash-up");
    // a price with no band still deserves a visible move
    expect(toneClass("null")).toContain("realtime-flash-up");
  });

  it("re-keys on the tone so a band change restarts the animation", () => {
    const { container } = render(<RealtimeValue pulse={pulse} tone="floor">1</RealtimeValue>);
    expect((container.firstElementChild as HTMLElement).dataset.flashTone).toBe("floor");
  });

  it("no pulse means no flash at all", () => {
    const { container } = render(<RealtimeValue tone="ceiling">1</RealtimeValue>);
    expect((container.firstElementChild as HTMLElement).className).not.toContain("realtime-flash");
  });
});

describe("quoteCell — TRD_AMT follows the matched price", () => {
  it("carries the price band as both colour and tone", () => {
    const atCeiling = quoteCell(row(30, { tradedQuantity: 300 }), "tradedQuantity");
    expect(atCeiling.text).toBe("300");
    expect(atCeiling.color).toBe(MARKET_COLOR.ceiling);
    expect(atCeiling.tone).toBe("ceiling");

    const atRef = quoteCell(row(25, { tradedQuantity: 300 }), "tradedQuantity");
    expect(atRef.color).toBe(MARKET_COLOR.flat);
    expect(atRef.tone).toBe("flat");

    const below = quoteCell(row(23, { tradedQuantity: 300 }), "tradedQuantity");
    expect(below.color).toBe(MARKET_COLOR.down);
  });

  it("renders a non-positive size as unknown, never a literal 0", () => {
    for (const qty of [0, -5, null, undefined]) {
      const cell = quoteCell(row(27, { tradedQuantity: qty }), "tradedQuantity");
      expect(cell.text).toBe("—");
      expect(cell.tone).toBeUndefined();
    }
  });

  it("price cells expose the tone too, so the whole row flashes consistently", () => {
    expect(quoteCell(row(30), "last").tone).toBe("ceiling");
    expect(quoteCell(row(30), "ref").tone).toBe("flat");
    expect(quoteCell(row(30), "ceiling").tone).toBe("ceiling");
    expect(quoteCell(row(30), "floor").tone).toBe("floor");
  });
});

describe("white-text columns flash neutral, not up/down", () => {
  it("IV and VOLUME carry the neutral tone", () => {
    for (const key of ["ivBid", "ivTrade", "ivAsk", "vol"] as const) {
      expect(quoteCell(row(27), key).tone).toBe("neutral");
    }
  });

  it("a rising IV is not washed green", () => {
    const { container } = render(
      <RealtimeValue pulse={pulse} tone="neutral">34.2%</RealtimeValue>,
    );
    const cls = (container.firstElementChild as HTMLElement).className;
    expect(cls).toContain("realtime-flash-neutral");
    expect(cls).not.toContain("realtime-flash-up");
  });

  it("price columns keep their band tone, so the two languages stay distinct", () => {
    expect(quoteCell(row(30), "last").tone).toBe("ceiling");
    expect(quoteCell(row(27), "vol").tone).toBe("neutral");
  });
});
