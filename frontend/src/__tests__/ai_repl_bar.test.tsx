import { describe, it, expect, beforeEach } from "vitest";
import { renderMarkup } from "./test_fixtures/render_markup";
import { AiReplBar, getActivityLabel } from "../features/ai_assistant/ai_repl_bar";
import type { ResearchContextEnvelope } from "../data/ai/use_ai_chat";

/**
 * Coverage carried over from the retired `ai_assistant_bubble.test.tsx`:
 * the assistant surface must never leak provider secrets, and it must accept the
 * canonical research-context envelope without throwing.
 */
describe("AiReplBar — assistant surface, context awareness & secret hygiene", () => {
  beforeEach(() => {
    (globalThis as any).window = (globalThis as any).window || {};
    (globalThis as any).window.localStorage = {
      _s: {} as Record<string, string>,
      getItem(k: string) { return this._s[k] ?? null; },
      setItem(k: string, v: string) { this._s[k] = String(v); },
      removeItem(k: string) { delete this._s[k]; },
      clear() { this._s = {}; },
    };
  });

  it("renders the REPL input, prompt glyph and the three controls", () => {
    const html = renderMarkup(<AiReplBar />);
    expect(html).toContain('aria-label="Ask the research assistant"');
    expect(html).toContain("ask about pricing, greeks, contract terms");
    expect(html).toContain('aria-label="New chat"');
    expect(html).toContain('aria-label="Chat history"');
    expect(html).toContain('aria-label="Attach file"');
  });

  it("never bundles or references OpenRouter API keys", () => {
    const html = renderMarkup(<AiReplBar />);
    expect(html).not.toContain("OPENROUTER_API_KEY");
    expect(html).not.toContain("sk-or-");
  });

  it("accepts the canonical research context envelope without throwing", () => {
    const ctx: ResearchContextEnvelope = {
      activePage: "dashboard",
      selectedInstrument: {
        symbol: "CVPB2615",
        instrumentType: "CW",
        underlyingSymbol: "VPB",
        strikePrice: 28500,
        ivBid: 0.21,
      },
      watchlist: ["CVPB2615", "CHPG2602"],
      realtimeStatus: "Market closed",
      dataMode: "last_session",
      marketSession: "CLOSED_POST_MARKET",
      marketSessionActive: false,
      quoteDisplayEligible: false,
      dataState: "LAST_SESSION",
      quoteAsOf: "2026-08-28T15:00:00+07:00",
      latestCompletedSession: "2026-08-28",
      calendarConfidence: "AUTHORITATIVE",
    } as ResearchContextEnvelope;

    const html = renderMarkup(<AiReplBar context={ctx} />);
    expect(html).toContain('aria-label="Ask the research assistant"');
  });

  it("activity labels are task-specific, never fabricated chain-of-thought", () => {
    expect(getActivityLabel("what is HPG doing?", "HPG")).toBe("Checking HPG data…");
    expect(getActivityLabel("delta for CVPB2615", "CVPB2615")).toBe("Reviewing CVPB2615 analytics…");
    expect(getActivityLabel("compare IV and HV")).toBe("Comparing volatility metrics…");
    expect(getActivityLabel("anything else")).toBe("Preparing response…");
  });
});
