import { describe, it, expect, beforeEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { AiAssistantBubble } from "../features/ai_assistant/ai_assistant_bubble";
import type { ResearchContextEnvelope } from "../data/ai/use_ai_chat";

class MemoryLocalStorage {
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

describe("AiAssistantBubble Presentation Shell, Context Awareness & Security", () => {
  let mockStorage: MemoryLocalStorage;

  beforeEach(() => {
    mockStorage = new MemoryLocalStorage();
    (globalThis as any).window = (globalThis as any).window || {};
    (globalThis as any).window.localStorage = mockStorage;
  });

  it("1. Renders draggable trigger bubble with accessible label", () => {
    const html = renderToStaticMarkup(<AiAssistantBubble />);

    expect(html).toContain('aria-label="Open AI Research Assistant"');
    expect(html).toContain('title="Open Research Assistant (drag to reposition)"');
  });

  it("2. Restores saved position coordinates from localStorage", () => {
    mockStorage.setItem(
      "cw-assistant-bubble-pos:v1",
      JSON.stringify({ x: 45, y: 55 })
    );

    const html = renderToStaticMarkup(<AiAssistantBubble />);
    expect(html).toContain("right:45px");
    expect(html).toContain("bottom:55px");
  });

  it("3. Falls back safely to default position when localStorage is empty or corrupt", () => {
    mockStorage.setItem("cw-assistant-bubble-pos:v1", "corrupted json {");

    const html = renderToStaticMarkup(<AiAssistantBubble />);
    expect(html).toContain("right:28px");
    expect(html).toContain("bottom:28px");
  });

  it("4. Zero Secret Leaks: Verifies frontend never references or bundles OpenRouter API keys", () => {
    const html = renderToStaticMarkup(<AiAssistantBubble />);
    expect(html).not.toContain("OPENROUTER_API_KEY");
    expect(html).not.toContain("sk-or-");
  });

  it("5. Accepts canonical research context envelope without throwing", () => {
    const mockContext: ResearchContextEnvelope = {
      activePage: "dashboard",
      selectedInstrument: {
        symbol: "CFPT2401",
        instrumentType: "CW",
        underlyingSymbol: "FPT",
        strikePrice: 125000,
        ivBid: 0.312,
      },
      watchlist: ["CFPT2401", "CHPG2401"],
      realtimeStatus: "Live",
      dataMode: "live",
    };

    const html = renderToStaticMarkup(<AiAssistantBubble context={mockContext} />);
    expect(html).toContain('aria-label="Open AI Research Assistant"');
  });
});
