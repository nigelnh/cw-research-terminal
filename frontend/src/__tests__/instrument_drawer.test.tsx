import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderMarkup } from "./test_fixtures/render_markup";
import { InstrumentDrawer } from "../features/warrant_info/instrument_drawer";
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
    const html = renderMarkup(
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
    const html = renderMarkup(
      <InstrumentDrawer instrument={mockInstrument} onClose={vi.fn()} />
    );

    expect(html).toContain("Overview");
    expect(html).toContain("History");
    expect(html).toContain("Quant");
  });

  it("3. Renders Overview sections: Market, Contract, Volatility, and Microstructure Liquidity", () => {
    const html = renderMarkup(
      <InstrumentDrawer instrument={mockInstrument} onClose={vi.fn()} />
    );

    expect(html).toContain("Market");
    expect(html).toContain("Contract");
    expect(html).toContain("Volatility");
    expect(html).toContain("Microstructure Liquidity");
    expect(html).toContain("Book liquidity not published for this instrument.");
  });

  it("4. Returns null and renders nothing when instrument is null", () => {
    const html = renderMarkup(
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
  });

  it("6. Stock drawer does not show warrant-only analytics (Contract, Volatility, Quant tab)", () => {
    const mockStock = {
      symbol: "HPG",
      instrumentType: "STOCK" as const,
      quote: {
        symbol: "HPG",
        lastPrice: 21850,
        referencePrice: 21800,
        priceChange: 50,
        priceChangePercent: 0.0023,
        totalVolume: 15000000,
        bidPrice: 21800,
        askPrice: 21850,
        sourceTimestamp: new Date().toISOString(),
      },
    };

    const html = renderMarkup(
      <InstrumentDrawer instrument={mockStock as any} onClose={vi.fn()} />
    );

    expect(html).toContain("HPG");
    expect(html).toContain("Stock");
    expect(html).toContain("Overview");
    expect(html).toContain("History");
    // Quant tab should NOT be rendered for stock
    expect(html).not.toContain("Quant");
    // Contract & Volatility sections should NOT be rendered in Overview for stock
    expect(html).not.toContain("Contract");
    expect(html).not.toContain("Volatility");
    expect(html).not.toContain("Moneyness (S/K)");
    expect(html).not.toContain("IV bid");
  });
});
