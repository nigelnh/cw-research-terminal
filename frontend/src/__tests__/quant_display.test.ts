import { describe, it, expect } from "vitest";
import { computeSpread, formatPct, daysUntil, contractStateLabel } from "@/domain/quant_display";

describe("computeSpread - the one canonical spread convention", () => {
  it("normal two-sided quote: abs = ask-bid, pct = 100*(ask-bid)/mid", () => {
    const { abs, pct } = computeSpread(800, 820);
    expect(abs).toBe(20);
    // mid = 810 -> 20/810*100
    expect(pct).toBeCloseTo((20 / 810) * 100, 10);
  });

  it("bid === ask -> zero spread, still valid", () => {
    expect(computeSpread(500, 500)).toEqual({ abs: 0, pct: 0 });
  });

  it("missing bid -> unavailable", () => {
    expect(computeSpread(null, 820)).toEqual({ abs: null, pct: null });
    expect(computeSpread(undefined, 820)).toEqual({ abs: null, pct: null });
  });

  it("missing ask -> unavailable", () => {
    expect(computeSpread(800, null)).toEqual({ abs: null, pct: null });
  });

  it("zero / negative prices -> unavailable (never coerced)", () => {
    expect(computeSpread(0, 820)).toEqual({ abs: null, pct: null });
    expect(computeSpread(800, 0)).toEqual({ abs: null, pct: null });
    expect(computeSpread(-1, 820)).toEqual({ abs: null, pct: null });
  });

  it("crossed quote (ask < bid) -> unavailable", () => {
    expect(computeSpread(820, 800)).toEqual({ abs: null, pct: null });
  });

  it("NaN -> unavailable", () => {
    expect(computeSpread(NaN, 820)).toEqual({ abs: null, pct: null });
  });
});

describe("formatPct - decimal fraction to percent", () => {
  it("0.325 -> 32.5%", () => expect(formatPct(0.325)).toBe("32.5%"));
  it("null / NaN -> em-dash", () => {
    expect(formatPct(null)).toBe("—");
    expect(formatPct(NaN)).toBe("—");
  });
});

describe("daysUntil - matches backend calendar DTE (floored at 0)", () => {
  it("future date -> positive day count", () => {
    const d = daysUntil("2026-09-10", new Date("2026-08-29T10:00:00+07:00"));
    expect(d).toBe(12);
  });
  it("past date -> 0, never negative", () => {
    expect(daysUntil("2026-01-01", new Date("2026-08-29T10:00:00+07:00"))).toBe(0);
  });
  it("null -> null", () => expect(daysUntil(null)).toBeNull());
});

describe("contractStateLabel", () => {
  it("maps known states", () => {
    expect(contractStateLabel("LAST_TRADING_DAY")).toBe("Last trading day");
    expect(contractStateLabel("PENDING_MATURITY")).toContain("settlement");
  });
  it("unknown / null -> em-dash", () => {
    expect(contractStateLabel(null)).toBe("—");
    expect(contractStateLabel("UNKNOWN")).toBe("—");
  });
});
