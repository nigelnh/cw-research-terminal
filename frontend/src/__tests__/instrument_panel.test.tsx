import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderMarkup } from "./test_fixtures/render_markup";
import { InstrumentPanel } from "../features/warrant_info/instrument_panel";
import { createDefaultWatchlist, defaultWatchlistStorage } from "../domain/models/watchlist";
import { resetWatchlistMemoryForTests } from "../data/watchlist/use_watchlist";
import { mapRawSnapshotToQuote } from "../data/backend/mappers/map_snapshot";

vi.mock("@/data/query/use_fundamentals", () => ({
  useFundamentals: () => ({ data: null, quarters: [], isLoading: false, isError: false }),
}));
vi.mock("@/data/query/use_traded_log", () => ({
  useTradedLog: () => ({ items: [], sessionDate: null, sideBasis: null, isLoading: false, isError: false }),
}));

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
    expect(html).toContain("LAST_TRD_DATE");
    expect(html).toContain("DTE");
    expect(html).not.toMatch(/>\s*\d+d\s*</); // never "24d"
  });

  it("3b. OVERVIEW right pane is TRADED LOGS, with an honest empty state per session", () => {
    // The tape is now server-backed and survives the close, so the closed-market copy is
    // about the LAST session having no prints - not about the feature being unavailable.
    const closed = renderMarkup(
      <InstrumentPanel instrument={cw} marketSessionActive={false} onClose={vi.fn()} />,
    );
    expect(closed).toContain("TRADED LOGS");
    expect(closed).toContain("No matches recorded for the last session.");
    expect(closed).not.toContain("PRICE HISTORY");
    expect(closed).not.toContain("not yet wired");

    const live = renderMarkup(
      <InstrumentPanel instrument={cw} marketSessionActive={true} onClose={vi.fn()} />,
    );
    expect(live).toContain("No matches yet this session.");
  });

  it("4. CONFLICTING metadata -> explained in the panel, analytics withheld as em-dash", () => {
    const conflicting = { ...cw, metadataVerification: "CONFLICTING" as const };
    const html = renderMarkup(
      <InstrumentPanel instrument={conflicting} marketSessionActive={false} onClose={vi.fn()} />,
    );
    expect(html).toContain("CONFLICTING METADATA");
    expect(html).toContain("Quant withheld until reconciled");
  });

  it("5. stock instrument -> STOCK kind line without CW-only metric rows", () => {
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
    for (const label of ["IV_BID", "IV_TRD", "IV_ASK", "STRIKE", "RATIO", "LAST_TRD_DATE", "DTE", "ISSUER"]) {
      expect(html).not.toContain(label);
    }
  });

  it("6. STATS uses the resolved dashboard quote and its explicit change, not a reference-only WS object", () => {
    const quote = mapRawSnapshotToQuote({ Symbol: "HPG", Traded: 21.65, Ref: 21.6,
      change: -0.45, ChangePercent: -0.0204, Total_Vol: 9472000 });
    const html = renderMarkup(<InstrumentPanel
      instrument={{ symbol: "HPG", instrumentType: "STOCK",
        quote: mapRawSnapshotToQuote({ Symbol: "HPG", Ref: 21.6 }) }}
      dashRow={{ symbol: "HPG", quote, analytics: null, trackedRealtime: true,
        displayState: "LAST_SESSION", provenance: {
          quote: { state: "LAST_SESSION", source: "SNAPSHOT_FINAL" },
          book: { state: "UNAVAILABLE", source: "NONE" },
        } }} marketSessionActive={false} onClose={vi.fn()} />);
    expect(html).toContain("21,650");
    expect(html).toContain("9,472,000");
    expect(html).toContain("−450");
    expect(html).not.toContain("+50");
  });

  it("7. QUANT renders the canonical live top-three book instead of placeholder cards", () => {
    const quote = mapRawSnapshotToQuote({
      Symbol: "CFPT2401", Traded: 590, Ref: 550,
      Bid1_Prc: 570, Bid1_Qty: 10_000, Ask1_Prc: 580, Ask1_Qty: 20_000,
      Bid2_Prc: 560, Bid2_Qty: 30_000, Ask2_Prc: 590, Ask2_Qty: 40_000,
      Bid3_Prc: 550, Bid3_Qty: 50_000, Ask3_Prc: 600, Ask3_Qty: 60_000,
    });
    const html = renderMarkup(<InstrumentPanel
      instrument={cw}
      dashRow={{ symbol: cw.symbol, quote, analytics: null, trackedRealtime: true,
        displayState: "LIVE", provenance: {
          quote: { state: "LIVE", source: "VNSTOCK_JS_SSI_REALTIME" },
          book: { state: "LIVE", source: "VNSTOCK_JS_SSI_REALTIME" },
        } }}
      marketSessionActive={true}
      initialTab="quant"
      onClose={vi.fn()}
    />);
    expect(html).toContain("TOP-3 ORDER BOOK · LIVE");
    expect(html).toContain("BID DEPTH");
    expect(html).toContain("ASK DEPTH");
    expect(html).toContain("BID SHARE");
    expect(html).toContain("90,000");
    expect(html).toContain("120,000");
    expect(html).not.toContain("PRICE DEPTH · live");
  });
});
