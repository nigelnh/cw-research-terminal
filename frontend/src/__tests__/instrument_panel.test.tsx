import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderMarkup } from "./test_fixtures/render_markup";
import { InstrumentPanel } from "../features/warrant_info/instrument_panel";
import { createDefaultWatchlist, defaultWatchlistStorage } from "../domain/models/watchlist";
import { resetWatchlistMemoryForTests } from "../data/watchlist/use_watchlist";

describe("InstrumentPanel — bottom split panel", () => {
  beforeEach(() => {
    (globalThis as any).window = (globalThis as any).window || {};
    (globalThis as any).window.localStorage = {
      _s: {} as Record<string, string>,
      getItem(k: string) { return this._s[k] ?? null; },
      setItem(k: string, v: string) { this._s[k] = String(v); },
      removeItem(k: string) { delete this._s[k]; },
      clear() { this._s = {}; },
    };
    const fresh = createDefaultWatchlist();
    defaultWatchlistStorage.saveWatchlist(fresh);
    resetWatchlistMemoryForTests(fresh);
  });

  const cw = {
    symbol: "CFPT2401",
    instrumentType: "CW" as const,
    underlyingSymbol: "FPT",
    issuer: "SSI",
    strikePrice: 120000,
    exerciseRatio: 2,
    maturityDate: "2026-12-31",
    lastTradingDate: "2026-12-28",
  };

  it("1. no instrument -> renders nothing (the AI assistant now lives in the Orbit panel)", () => {
    const html = renderMarkup(
      <InstrumentPanel instrument={null} marketSessionActive={false} onClose={vi.fn()} />,
    );
    expect(html.trim()).toBe("");
  });

  it("2. CW instrument -> symbol, kind line, OVERVIEW/QUANT tabs, WATCH control", () => {
    const html = renderMarkup(
      <InstrumentPanel instrument={cw} marketSessionActive={false} onClose={vi.fn()} />,
    );
    expect(html).toContain("CFPT2401");
    expect(html).toContain("COVERED WARRANT · SSI · FPT");
    expect(html).toContain("OVERVIEW");
    expect(html).toContain("QUANT");
    expect(html).toContain('aria-label="Close instrument"');
    // default watchlist does not contain CFPT2401
    expect(html).toContain("+ WATCH");
  });

  it("3. OVERVIEW shows contract terms; DTE is a bare number (no 'd' suffix)", () => {
    const html = renderMarkup(
      <InstrumentPanel instrument={cw} marketSessionActive={false} onClose={vi.fn()} />,
    );
    expect(html).toContain("STRIKE");
    expect(html).toContain("120,000");
    expect(html).toContain("MATURITY");
    expect(html).toContain("DTE");
    expect(html).not.toMatch(/>\s*\d+d\s*</); // never "24d"
  });

  it("3b. OVERVIEW right pane is TRADED LOGS (session-gated, honest empty state)", () => {
    const closed = renderMarkup(
      <InstrumentPanel instrument={cw} marketSessionActive={false} onClose={vi.fn()} />,
    );
    expect(closed).toContain("TRADED LOGS");
    expect(closed).toContain("unavailable outside a live session");
    expect(closed).not.toContain("PRICE HISTORY");

    const live = renderMarkup(
      <InstrumentPanel instrument={cw} marketSessionActive={true} onClose={vi.fn()} />,
    );
    expect(live).toContain("not yet wired");
  });

  it("4. CONFLICTING metadata -> explained in the panel, analytics withheld as em-dash", () => {
    const conflicting = { ...cw, metadataVerification: "CONFLICTING" as const };
    const html = renderMarkup(
      <InstrumentPanel instrument={conflicting} marketSessionActive={false} onClose={vi.fn()} />,
    );
    expect(html).toContain("CONFLICTING METADATA");
    expect(html).toContain("Quant withheld until reconciled");
  });

  it("5. stock instrument -> STOCK kind line, no warrant-only contract rows", () => {
    const html = renderMarkup(
      <InstrumentPanel
        instrument={{ symbol: "HPG", instrumentType: "STOCK" }}
        marketSessionActive={false}
        onClose={vi.fn()}
      />,
    );
    expect(html).toContain("STOCK · HOSE");
    expect(html).not.toContain("COVERED WARRANT");
    expect(html).not.toContain("MONEYNESS S/K");
    expect(html).not.toContain("IV BID");
    expect(html).not.toContain("STRIKE");
  });
});
