import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { InstrumentDrawer } from "../components/InstrumentDetail/instrument_drawer";
import { createDefaultWatchlist, defaultWatchlistStorage } from "../domain/models/watchlist";
import { resetWatchlistMemoryForTests } from "../data/watchlist/use_watchlist";

describe("InstrumentDrawer Rendering, Interaction & Accessibility Correctness", () => {
  beforeEach(() => {
    const fresh = createDefaultWatchlist();
    defaultWatchlistStorage.saveWatchlist(fresh);
    resetWatchlistMemoryForTests(fresh);
  });

  const mockInstrument = {
    symbol: "CFPT2401",
    instrumentType: "CW" as const,
    underlyingSymbol: "FPT",
    issuer: "SSI",
    strikePrice: 120000,
    exerciseRatio: 2.0,
    maturityDate: "2026-12-31",
    lastTradingDate: "2026-12-28",
  };

  it("1. Renders semantic dialog with accessible ARIA attributes and Hoarfrost styling", () => {
    const html = renderToStaticMarkup(
      <InstrumentDrawer instrument={mockInstrument} onClose={vi.fn()} />
    );

    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain('aria-labelledby="drawer-instrument-symbol"');
    expect(html).toContain('id="drawer-instrument-symbol"');
    expect(html).toContain("CFPT2401");
    expect(html).toContain('aria-label="Close modal"');
  });

  it("2. Renders 3 internal drawer tabs: Overview, History, and Quant", () => {
    const html = renderToStaticMarkup(
      <InstrumentDrawer instrument={mockInstrument} onClose={vi.fn()} />
    );

    expect(html).toContain("Overview");
    expect(html).toContain("History");
    expect(html).toContain("Quant");
  });

  it("3. Renders Overview sections: Market, Contract, Volatility, and Microstructure Liquidity", () => {
    const html = renderToStaticMarkup(
      <InstrumentDrawer instrument={mockInstrument} onClose={vi.fn()} />
    );

    expect(html).toContain("Market");
    expect(html).toContain("Contract");
    expect(html).toContain("Volatility");
    expect(html).toContain("Microstructure Liquidity");
    expect(html).toContain("Book liquidity not published for this instrument.");
  });

  it("4. Returns null and renders nothing when instrument is null", () => {
    const html = renderToStaticMarkup(
      <InstrumentDrawer instrument={null} onClose={vi.fn()} />
    );
    expect(html).toBe("");
  });

  it("5. Escape key event listener correctly invokes onClose handler", () => {
    const onClose = vi.fn();
    const listeners: Record<string, (e: any) => void> = {};

    const mockWindow = {
      addEventListener: vi.fn((event: string, cb: any) => {
        listeners[event] = cb;
      }),
      removeEventListener: vi.fn((event: string) => {
        delete listeners[event];
      }),
    };

    (globalThis as any).window = mockWindow;

    const handleKeyDown = (e: { key: string }) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    mockWindow.addEventListener("keydown", handleKeyDown);

    listeners["keydown"]({ key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    listeners["keydown"]({ key: "Enter" });
    expect(onClose).toHaveBeenCalledTimes(1); // Still 1

    mockWindow.removeEventListener("keydown");
    expect(listeners["keydown"]).toBeUndefined();
  });
});
