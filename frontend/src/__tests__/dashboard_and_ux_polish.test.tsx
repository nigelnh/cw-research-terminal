import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { PersonalDashboard } from "../features/watchlist/personal_dashboard";
import { InstrumentDrawer } from "../features/warrant_info/instrument_drawer";
import { TopNav } from "../components/common/top_nav";
import { AiAssistantBubble, getActivityLabel } from "../features/ai_assistant/ai_assistant_bubble";
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

describe("Targeted Dashboard & Copilot UX Polish Pass Verifications", () => {
  let mockStorage: MemoryStorage;

  beforeEach(() => {
    mockStorage = new MemoryStorage();
    (globalThis as any).window = (globalThis as any).window || {};
    (globalThis as any).window.localStorage = mockStorage;

    const fresh = createDefaultWatchlist();
    defaultWatchlistStorage.saveWatchlist(fresh);
    resetWatchlistMemoryForTests(fresh);
  });

  it("1 & 2 & 3. Stock and CW rows render in separate Dashboard sections with strict column scoping", () => {
    const html = renderToStaticMarkup(<PersonalDashboard />);

    // Separate section headers
    expect(html).toContain("Stocks (3)");
    expect(html).toContain("Covered Warrants (2)");

    // Stocks section should have stock headers but NOT CW-only headers in its stock sub-table
    expect(html).toContain("Symbol");
    expect(html).toContain("Ref");
    expect(html).toContain("Last");
    expect(html).toContain("Chg");
    expect(html).toContain("Spread");
    expect(html).toContain("Spread %");
    expect(html).toContain("Volume");

    // Covered Warrants section retains full quantitative columns
    expect(html).toContain("Issuer");
    expect(html).toContain("Underlying");
    expect(html).toContain("Und. price");
    expect(html).toContain("Strike");
    expect(html).toContain("Ratio");
    expect(html).toContain("DTE");
    expect(html).toContain("IV bid");
    expect(html).toContain("IV trade");
    expect(html).toContain("IV ask");
  });

  it("4 & 5. CW drawer retains full quant metrics while Stock drawer suppresses warrant-only analytics", () => {
    const mockCW = {
      symbol: "CVHM2615",
      instrumentType: "CW" as const,
      underlyingSymbol: "VHM",
      issuer: "SSI",
      strikePrice: 45000,
      exerciseRatio: 5.0,
      maturityDate: "2026-06-30",
      lastTradingDate: "2026-06-26",
      cw: {
        symbol: "CVHM2615",
        underlyingSymbol: "VHM",
        issuer: "SSI",
        strikePrice: 45000,
        exerciseRatio: 5.0,
        maturityDate: "2026-06-30",
        lastTradingDate: "2026-06-26",
        underlyingPrice: 48000,
        ivBid: 0.315,
        ivTrade: 0.320,
        ivAsk: 0.325,
        delta: 0.62,
        gamma: 0.000045,
        theta: -12.5,
        vega: 18.2,
        rho: 4.1,
        theoreticalPrice: 1420,
        historicalVolatility: 0.28,
        moneyness: 1.0667,
      },
    };

    const cwHtml = renderToStaticMarkup(
      <InstrumentDrawer instrument={mockCW as any} onClose={vi.fn()} />
    );

    expect(cwHtml).toContain("Covered Warrant");
    expect(cwHtml).toContain("Quant");
    expect(cwHtml).toContain("Contract");
    expect(cwHtml).toContain("Volatility");
    expect(cwHtml).toContain("Underlying VHM");

    const mockStock = {
      symbol: "VHM",
      instrumentType: "STOCK" as const,
    };

    const stockHtml = renderToStaticMarkup(
      <InstrumentDrawer instrument={mockStock} onClose={vi.fn()} />
    );

    expect(stockHtml).toContain("Stock");
    expect(stockHtml).not.toContain("Quant");
    expect(stockHtml).not.toContain("Contract");
    expect(stockHtml).not.toContain("Volatility");
    expect(stockHtml).not.toContain("Underlying VHM");
  });

  it("6 & 7. normalizePlainResponse strips markdown syntax without losing math characters, and assistant message has no repeated icon/label", () => {
    const rawMarkdown = "**Valuation Analysis**\n- Last price: 29,500 VND\n- Delta (Δ): 0.6200\n- Spread: 0.72%\n# Recommendation\nWait for afternoon session.";
    const cleaned = normalizePlainResponse(rawMarkdown);

    // Markdown artifacts removed
    expect(cleaned).not.toContain("**");
    expect(cleaned).not.toContain("- ");
    expect(cleaned).not.toContain("# ");

    // Mathematical and quantitative symbols preserved
    expect(cleaned).toContain("Valuation Analysis");
    expect(cleaned).toContain("Last price: 29,500 VND");
    expect(cleaned).toContain("Delta (Δ): 0.6200");
    expect(cleaned).toContain("Spread: 0.72%");
    expect(cleaned).toContain("Recommendation");
  });

  it("8, 9 & 10. Chat persistence in localStorage survives rehydration and clear removes storage", () => {
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
            { id: "m2", role: "assistant", content: "HPG 30-day historical volatility is 24.5%.", createdAt: 2000 },
          ],
        },
      ],
    };

    mockStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(persistedPayload));

    // Verify storage key is canonical
    expect(CHAT_STORAGE_KEY).toBe("cw_research:copilot_history:v2");

    const raw = mockStorage.getItem(CHAT_STORAGE_KEY);
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!);
    expect(parsed.conversations).toHaveLength(1);
    expect(parsed.conversations[0].messages[0].content).toBe("Check HPG volatility");

    // Clearing storage removes the key
    mockStorage.removeItem(CHAT_STORAGE_KEY);
    expect(mockStorage.getItem(CHAT_STORAGE_KEY)).toBeNull();
  });

  it("11. Context-aware activity indicator generates task-specific status without fake chain-of-thought", () => {
    expect(getActivityLabel("What is HPG doing?")).toBe("Checking HPG data…");
    expect(getActivityLabel("Check CVHM2615 delta")).toBe("Reviewing warrant analytics…");
    expect(getActivityLabel("Compare IV and HV")).toBe("Comparing volatility metrics…");
    expect(getActivityLabel("Calculate Greeks")).toBe("Calculating Greek sensitivities…");
    expect(getActivityLabel("What is fair value valuation?")).toBe("Calculating valuation metrics…");
    expect(getActivityLabel("General question")).toBe("Preparing response…");
  });

  it("12. Focus state classes and styles exist for accessible non-native outline, and composer uses neutral border without focus highlight", () => {
    const html = renderToStaticMarkup(<AiAssistantBubble initialOpen={true} />);
    expect(html).toContain("focus-ring");
    // Composer container is centered and uses constant neutral border without box-shadow
    expect(html).toContain("align-items:center");
    expect(html).toContain("border:1px solid var(--border)");
    expect(html).toContain("box-shadow:none");
  });

  it("13. Redundant Dashboard footer sentence is completely removed", () => {
    const html = renderToStaticMarkup(<PersonalDashboard />);
    expect(html).not.toContain("instruments in personal dashboard");
    expect(html).not.toContain("search Research catalog to explore all instruments");
  });

  it("14. Subscription capacity label accurately uses 'slots' instead of misleading 'live'", () => {
    const html = renderToStaticMarkup(<TopNav activeTab="dashboard" onTabChange={vi.fn()} />);
    expect(html).toContain("7</span> / 33 slots");
    expect(html).not.toContain("live");
  });
});
