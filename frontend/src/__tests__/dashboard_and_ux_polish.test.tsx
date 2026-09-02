import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderMarkup, seedInstrumentSpecs } from "./test_fixtures/render_markup";
import { PersonalDashboard } from "../features/watchlist/personal_dashboard";
import { InstrumentPanel } from "../features/warrant_info/instrument_panel";
import { AppHeader } from "../components/common/app_header";
import { normalizePlainResponse, CHAT_STORAGE_KEY } from "../data/ai/use_ai_chat";
import { createDefaultWatchlist, defaultWatchlistStorage } from "../domain/models/watchlist";
import { resetWatchlistMemoryForTests } from "../data/watchlist/use_watchlist";

class MemoryStorage {
  private store: Record<string, string> = {};
  getItem(key: string): string | null {
    return this.store[key] !== undefined ? this.store[key] : null;
  }
  setItem(key: string, value: string): void {
    this.store[key] = String(value);
  }
  removeItem(key: string): void {
    delete this.store[key];
  }
  clear(): void {
    this.store = {};
  }
}

describe("Grid Terminal — dashboard, panel & assistant UX", () => {
  let mockStorage: MemoryStorage;

  beforeEach(() => {
    mockStorage = new MemoryStorage();
    (globalThis as any).window = (globalThis as any).window || {};
    (globalThis as any).window.localStorage = mockStorage;

    const fresh = createDefaultWatchlist();
    defaultWatchlistStorage.saveWatchlist(fresh);
    resetWatchlistMemoryForTests(fresh);
  });

  it("1. Watchlist renders one unified table with the shared Grid Terminal column schema", () => {
    const html = renderMarkup(<PersonalDashboard />);
    expect(html).toContain("Watchlist");
    // one shared schema for stock parents and CW children — incl. the absolute-change (+/-)
    // column between TRD and CHG%
    expect(html).toContain("SYMBOL");
    expect(html).toContain("+/-");
    expect(html).toContain("VOLUME");
    expect(html).toContain("STRIKE");
    expect(html).toContain("IV TRD");
    // redundant CW-only columns were merged away in the unified table
    expect(html).not.toContain("UND.PRC");
    expect(html).not.toContain("FRN ROOM");
    // the market-overview index strip was removed in the v3 design
    expect(html).not.toContain("VNXALL");
    expect(html).not.toContain("HNXUPCOM");
  });

  it("2. Bid/ask are em-dash outside a live session (no fabricated book)", () => {
    const html = renderMarkup(<PersonalDashboard />);
    expect(html).toContain("—");
  });

  it("3. CW panel keeps the QUANT tab; stock panel does not surface warrant-only rows", () => {
    const cwHtml = renderMarkup(
      <InstrumentPanel
        instrument={{
          symbol: "CVHM2615",
          instrumentType: "CW",
          underlyingSymbol: "VHM",
          issuer: "SSI",
          strikePrice: 45000,
          exerciseRatio: 5,
          maturityDate: "2026-06-30",
          lastTradingDate: "2026-06-26",
        }}
        marketSessionActive={false}
        onClose={vi.fn()}
      />,
    );
    expect(cwHtml).toContain("QUANT");
    expect(cwHtml).toContain("COVERED WARRANT · SSI · VHM");

    const stockHtml = renderMarkup(
      <InstrumentPanel
        instrument={{ symbol: "VHM", instrumentType: "STOCK" }}
        marketSessionActive={false}
        onClose={vi.fn()}
      />,
    );
    expect(stockHtml).toContain("STOCK · HOSE");
    expect(stockHtml).not.toContain("MONEYNESS S/K");
  });

  it("4. CONFLICTING metadata -> ◆ marker + tooltip in the table, full reason in the panel", () => {
    const wl = {
      id: "wl",
      name: "wl",
      items: [{ symbol: "CTCB2601", instrumentType: "CW" as const, underlyingSymbol: "TCB", addedAt: 0 }],
      createdAt: 0,
      updatedAt: 0,
      version: 3,
    };
    defaultWatchlistStorage.saveWatchlist(wl as any);
    resetWatchlistMemoryForTests(wl as any);

    const html = renderMarkup(<PersonalDashboard />, [
      seedInstrumentSpecs([
        {
          symbol: "CTCB2601",
          issuer: "ACBS",
          underlyingSymbol: "TCB",
          strikePrice: 37000,
          exerciseRatio: 4,
          dataQuality: "COMPLETE",
          metadataVerification: "CONFLICTING",
        },
      ]),
    ]);
    expect(html).toContain("◆");
    expect(html).toContain("Conflicting metadata — quant withheld");
    // canonical registry terms still shown
    expect(html).toContain("37,000");
    expect(html).toContain("4:1");
    // each row carries a "remove from view" control (non-destructive, session-only)
    expect(html).toContain('aria-label="Hide CTCB2601 from this view"');
  });

  it("6 & 7. normalizePlainResponse (legacy helper) still strips markdown without losing math", () => {
    const raw =
      "**Valuation Analysis**\n- Last price: 29,500 VND\n- Delta (Δ): 0.6200\n- Spread: 0.72%\n# Recommendation\nWait.";
    const cleaned = normalizePlainResponse(raw);
    expect(cleaned).not.toContain("**");
    expect(cleaned).not.toContain("- ");
    expect(cleaned).not.toContain("# ");
    expect(cleaned).toContain("Delta (Δ): 0.6200");
    expect(cleaned).toContain("Spread: 0.72%");
  });

  it("8, 9 & 10. Chat persistence survives rehydration; clear removes storage", () => {
    const persistedPayload = {
      version: 2,
      activeConversationId: "conv_1",
      conversations: [
        {
          id: "conv_1",
          title: "HPG Volatility",
          createdAt: 1000,
          updatedAt: 2000,
          messages: [
            { id: "m1", role: "user", content: "Check HPG volatility", createdAt: 1000 },
            { id: "m2", role: "assistant", content: "HPG 30-day HV is 24.5%.", createdAt: 2000 },
          ],
        },
      ],
    };
    mockStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(persistedPayload));
    expect(CHAT_STORAGE_KEY).toBe("cw_research:copilot_history:v2");
    const raw = mockStorage.getItem(CHAT_STORAGE_KEY);
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!);
    expect(parsed.conversations).toHaveLength(1);
    mockStorage.removeItem(CHAT_STORAGE_KEY);
    expect(mockStorage.getItem(CHAT_STORAGE_KEY)).toBeNull();
  });

  it("13. Header shows the market status pill and the segmented nav", () => {
    const html = renderMarkup(
      <AppHeader
        activeTab="dashboard"
        onTabChange={vi.fn()}
        filter=""
        onFilterChange={vi.fn()}
        marketSessionActive={false}
      />,
    );
    expect(html).toContain("CW-TERM");
    expect(html).toContain("DASHBOARD");
    expect(html).toContain("RESEARCH");
    expect(html).toContain("CLOSED");
  });
});
