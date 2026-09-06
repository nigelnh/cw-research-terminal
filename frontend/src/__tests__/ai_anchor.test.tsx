// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, fireEvent, cleanup, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const { getAiQuota } = vi.hoisted(() => ({ getAiQuota: vi.fn() }));
vi.mock("@/data/backend/backend_client", async (orig) => {
  const actual = (await orig()) as Record<string, unknown>;
  return { ...actual, backendClient: { getAiQuota } };
});

const authRef = vi.hoisted(() => ({ current: { user: null as { id: string } | null, status: "anonymous" } }));
vi.mock("@/data/auth", () => ({ useAuth: () => authRef.current }));

import { AiChatProvider } from "@/data/ai/ai_chat_provider";
import { AiAnchor } from "@/features/ai_assistant/ai_anchor";
import type { ResearchContextEnvelope } from "@/data/ai/use_ai_chat";
import { setAccessTokenProvider } from "@/data/backend/backend_client";

const POS_KEY = "cw_research:ai_anchor_pos:v1";

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <AiChatProvider>{children}</AiChatProvider>
    </QueryClientProvider>
  );
}

function renderAnchor() {
  return render(<AiAnchor context={{ activePage: "dashboard" }} />, { wrapper: Wrapper });
}

beforeEach(() => {
  window.localStorage.clear();
  window.innerWidth = 1440;
  window.innerHeight = 900;
  authRef.current = { user: null, status: "anonymous" };
  getAiQuota.mockReset();
  getAiQuota.mockResolvedValue({ enabled: false, tier: "guest" });
});
afterEach(cleanup);

function openAnchorPanel() {
  const btn = screen.getByRole("button", { name: /open research assistant/i });
  fireEvent.pointerDown(btn, { button: 0, clientX: 1390, clientY: 850, pointerId: 1 });
  fireEvent.pointerUp(btn, { clientX: 1390, clientY: 850, pointerId: 1 });
}

describe("AiAnchor — draggable assistant anchor + fixed conversation panel", () => {
  it("defaults to the bottom-right corner of the viewport with a safe inset", () => {
    const { getByRole } = renderAnchor();
    const btn = getByRole("button", { name: /open research assistant/i });
    // 1440x900, anchor 34, edge 16 -> x = 1440-34-16 = 1390, y = 900-34-16 = 850
    expect(btn.style.left).toBe("1390px");
    expect(btn.style.top).toBe("850px");
    expect(btn.getAttribute("aria-expanded")).toBe("false");
  });

  it("a click (no drag) toggles the fixed-size conversation panel with a composer", () => {
    const { getByRole, queryByRole } = renderAnchor();
    const btn = getByRole("button", { name: /open research assistant/i });
    expect(queryByRole("dialog")).toBeNull();

    fireEvent.pointerDown(btn, { button: 0, clientX: 1390, clientY: 850, pointerId: 1 });
    fireEvent.pointerUp(btn, { clientX: 1390, clientY: 850, pointerId: 1 });

    const panel = getByRole("dialog", { name: /research assistant conversation/i });
    // fixed, bounded dimensions — never grows with content
    expect(panel.style.position).toBe("fixed");
    expect(panel.style.width).toBe("380px");
    expect(panel.style.height).toBe("468px");
    // the composer lives INSIDE the panel now (no separate bottom REPL)
    expect(panel.querySelector('textarea[aria-label="Ask the research assistant"]')).not.toBeNull();
    expect(getByRole("button", { name: /^send$/i })).toBeTruthy();
    expect(getByRole("button", { name: /close research assistant/i })).toBeTruthy();
  });

  it("a drag past the threshold moves the anchor, persists it, and does NOT open the panel", () => {
    const { getByRole, queryByRole } = renderAnchor();
    const btn = getByRole("button", { name: /open research assistant/i });

    fireEvent.pointerDown(btn, { button: 0, clientX: 1390, clientY: 850, pointerId: 1 });
    fireEvent.pointerMove(btn, { clientX: 900, clientY: 400, pointerId: 1 });
    fireEvent.pointerUp(btn, { clientX: 900, clientY: 400, pointerId: 1 });

    expect(queryByRole("dialog")).toBeNull(); // drag != click
    expect(btn.style.left).toBe("900px");
    expect(btn.style.top).toBe("400px");
    const saved = JSON.parse(window.localStorage.getItem(POS_KEY) || "{}");
    expect(saved).toEqual({ x: 900, y: 400 });
  });

  it("clamps a drag that would leave the viewport", () => {
    const { getByRole } = renderAnchor();
    const btn = getByRole("button", { name: /open research assistant/i });
    fireEvent.pointerDown(btn, { button: 0, clientX: 1390, clientY: 850, pointerId: 1 });
    fireEvent.pointerMove(btn, { clientX: 5000, clientY: 5000, pointerId: 1 });
    fireEvent.pointerUp(btn, { clientX: 5000, clientY: 5000, pointerId: 1 });
    // clamped to maxX = 1440-34-16 = 1390, maxY = 900-34-16 = 850
    expect(btn.style.left).toBe("1390px");
    expect(btn.style.top).toBe("850px");
  });

  it("restores a persisted position and re-clamps it on viewport resize", () => {
    window.localStorage.setItem(POS_KEY, JSON.stringify({ x: 1200, y: 800 }));
    const { getByRole } = renderAnchor();
    const btn = getByRole("button", { name: /open research assistant/i });
    expect(btn.style.left).toBe("1200px");

    window.innerWidth = 640;
    window.innerHeight = 480;
    fireEvent(window, new Event("resize"));
    // re-clamped so the anchor can never be lost off-screen
    expect(parseInt(btn.style.left)).toBeLessThanOrEqual(640 - 34 - 16);
    expect(parseInt(btn.style.top)).toBeLessThanOrEqual(480 - 34 - 16);
  });

  it("keyboard: Enter toggles the panel; the anchor exposes an accessible label + state", () => {
    const { getByRole, queryByRole } = renderAnchor();
    const btn = getByRole("button", { name: /open research assistant/i });
    fireEvent.keyDown(btn, { key: "Enter" });
    expect(queryByRole("dialog")).not.toBeNull();
    expect(btn.getAttribute("aria-expanded")).toBe("true");
  });

  it("the anchor button carries no rectangular focus outline (terminal focus language)", () => {
    const { getByRole } = renderAnchor();
    const btn = getByRole("button", { name: /open research assistant/i }) as HTMLElement;
    expect(btn.style.outline).toContain("none");
    expect(btn.className).not.toContain("focus-ring");
  });
});

function openPanel(getByRole: any) {
  const btn = getByRole("button", { name: /open research assistant/i });
  fireEvent.pointerDown(btn, { button: 0, clientX: 1390, clientY: 850, pointerId: 1 });
  fireEvent.pointerUp(btn, { clientX: 1390, clientY: 850, pointerId: 1 });
  return getByRole("dialog", { name: /research assistant conversation/i }) as HTMLElement;
}

describe("AiAnchor — unified composer inside the panel", () => {
  beforeEach(() => {
    // the composer submit calls the AI endpoint — stub it so nothing hits the network
    (globalThis as any).fetch = () =>
      Promise.resolve({
        ok: false,
        status: 503,
        headers: { get: () => null },
        json: () => Promise.resolve({}),
      } as any);
  });

  it("Enter submits (clears the field), Shift+Enter does not", () => {
    const { getByRole } = render(<AiAnchor context={{ activePage: "dashboard" } as ResearchContextEnvelope} />, {
      wrapper: Wrapper,
    });
    const panel = openPanel(getByRole);
    const ta = panel.querySelector("textarea") as HTMLTextAreaElement;

    fireEvent.change(ta, { target: { value: "line one" } });
    fireEvent.keyDown(ta, { key: "Enter", shiftKey: true });
    expect(ta.value).toBe("line one"); // shift+enter -> newline, no submit

    fireEvent.keyDown(ta, { key: "Enter" });
    expect(ta.value).toBe(""); // plain enter -> submit -> field + draft cleared
  });

  it("the composer has a fixed two-line input inside the terminal focus container", () => {
    const { getByRole } = render(<AiAnchor context={{ activePage: "dashboard" } as ResearchContextEnvelope} />, {
      wrapper: Wrapper,
    });
    const panel = openPanel(getByRole);
    const ta = panel.querySelector("textarea") as HTMLTextAreaElement;
    expect(ta.getAttribute("rows")).toBe("2");
    expect(getByRole("button", { name: "Upload files" })).toBeTruthy();
    // the composer form carries the class the terminal focus CSS targets
    expect(panel.querySelector("form.ai-composer")).not.toBeNull();
  });

  it("preserves a typed draft across close / reopen via localStorage", () => {
    const { getByRole, queryByRole } = render(
      <AiAnchor context={{ activePage: "dashboard" } as ResearchContextEnvelope} />,
      { wrapper: Wrapper },
    );
    let panel = openPanel(getByRole);
    fireEvent.change(panel.querySelector("textarea") as HTMLTextAreaElement, {
      target: { value: "half-written question" },
    });
    expect(window.localStorage.getItem("cw_research:ai_draft:v1")).toBe("half-written question");

    // close
    fireEvent.click(getByRole("button", { name: /minimize conversation/i }));
    expect(queryByRole("dialog")).toBeNull();
    // reopen -> draft restored
    panel = openPanel(getByRole);
    expect((panel.querySelector("textarea") as HTMLTextAreaElement).value).toBe("half-written question");
  });

  it("never bundles or references OpenRouter API keys", () => {
    const { getByRole } = render(<AiAnchor context={{ activePage: "dashboard" } as ResearchContextEnvelope} />, {
      wrapper: Wrapper,
    });
    const panel = openPanel(getByRole);
    const html = panel.outerHTML;
    expect(html).not.toContain("OPENROUTER_API_KEY");
    expect(html).not.toContain("sk-or-");
  });

  it("accepts the canonical research-context envelope without throwing", () => {
    const ctx: ResearchContextEnvelope = {
      activePage: "dashboard",
      selectedInstrument: { symbol: "CVPB2615", instrumentType: "CW", underlyingSymbol: "VPB", strikePrice: 28500, ivBid: 0.21 },
      watchlist: ["CVPB2615", "CHPG2602"],
      marketSession: "CLOSED_POST_MARKET",
      marketSessionActive: false,
      dataState: "LAST_SESSION",
    } as ResearchContextEnvelope;
    const { getByRole } = render(<AiAnchor context={ctx} />, { wrapper: Wrapper });
    const panel = openPanel(getByRole);
    expect(panel.querySelector('textarea[aria-label="Ask the research assistant"]')).not.toBeNull();
  });
});

describe("AiAnchor — the chat request is keyed to the signed-in caller", () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      headers: { get: () => null },
      json: () => Promise.resolve({}),
    });
    (globalThis as any).fetch = fetchSpy;
  });
  afterEach(() => setAccessTokenProvider(null));

  function submit(value: string) {
    const { getByRole } = render(<AiAnchor context={{ activePage: "dashboard" } as ResearchContextEnvelope} />, {
      wrapper: Wrapper,
    });
    const panel = openPanel(getByRole);
    const ta = panel.querySelector("textarea") as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value } });
    fireEvent.keyDown(ta, { key: "Enter" });
  }

  it("attaches the bearer token to POST /api/ai/chat when a session exists", async () => {
    setAccessTokenProvider(() => "tok-live-123");
    submit("rank my HPG warrants");
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toContain("/api/ai/chat");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-live-123");
  });

  it("sends no Authorization header for an anonymous caller", async () => {
    setAccessTokenProvider(() => null);
    submit("rank my HPG warrants");
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const [, init] = fetchSpy.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });
});

function seedConversation(messages: any[]) {
  window.localStorage.setItem(
    "cw_research:copilot_history:v2",
    JSON.stringify({
      version: 2,
      activeConversationId: "c1",
      conversations: [{ id: "c1", title: "t", createdAt: 1, updatedAt: 2, messages }],
    }),
  );
}

describe("AiAnchor — Markdown rendering + research trace", () => {
  it("renders assistant Markdown (bold, lists, headings) — not literal syntax", () => {
    seedConversation([
      { id: "u", role: "user", content: "structure please", createdAt: 1 },
      {
        id: "a",
        role: "assistant",
        createdAt: 2,
        content: "### Quant context\n\n- **IV:** 34.2%\n- **HV (22D):** 28.7%\n\nUse `get_quant`.",
      },
    ]);
    const { getByRole } = render(<AiAnchor context={{ activePage: "dashboard" } as ResearchContextEnvelope} />, {
      wrapper: Wrapper,
    });
    const panel = openPanel(getByRole);
    expect(panel.querySelector("strong")?.textContent).toContain("IV:");
    expect(panel.querySelectorAll("li").length).toBe(2);
    expect(panel.querySelector("code")?.textContent).toBe("get_quant");
    expect(panel.textContent).toContain("Quant context");
    // no raw markdown leaked
    expect(panel.textContent).not.toContain("### Quant context");
    expect(panel.textContent).not.toContain("**IV:**");
  });

  it("renders a compact research trace (tool display names + sanitised summaries)", () => {
    seedConversation([
      { id: "u", role: "user", content: "any HPG news?", createdAt: 1 },
      {
        id: "a",
        role: "assistant",
        createdAt: 2,
        content: "Per the HOSE filing on 2026-07-30…",
        trace: [
          { tool: "get_news", display_name: "Searching disclosures", context: "HOSE · HPG · recent", result_summary: "12 records found", duration_ms: 184, ok: true },
          { tool: "get_history", display_name: "Loading market history", context: "HPG · daily", result_summary: "248 bars loaded", duration_ms: 40, ok: true },
        ],
      },
    ]);
    const { getByRole } = render(<AiAnchor context={{ activePage: "dashboard" } as ResearchContextEnvelope} />, {
      wrapper: Wrapper,
    });
    const panel = openPanel(getByRole);
    const text = panel.textContent || "";
    expect(text).toContain("Research trace · 2 tools");
    // expand it
    fireEvent.click(getByRole("button", { name: /Research trace/i }));
    const expanded = panel.textContent || "";
    expect(expanded).toContain("Searching disclosures");
    expect(expanded).toContain("12 records found");
    expect(expanded).toContain("Loading market history");
    expect(expanded).toContain("248 bars loaded");
    // no raw payloads / reasoning
    expect(expanded).not.toContain("chain-of-thought");
  });
});

describe("AiAnchor — visible AI quota", () => {
  it("guest: shows today's usage, no sign-in upsell", async () => {
    getAiQuota.mockResolvedValue({
      enabled: true,
      tier: "guest",
      per_day: { limit: 8, used: 7, remaining: 1, resets_at: 0 },
      per_minute: { limit: 3, used: 0, remaining: 3, resets_at: 0 },
    });
    render(<AiAnchor context={{ activePage: "dashboard" } as ResearchContextEnvelope} />, { wrapper: Wrapper });
    openAnchorPanel();
    await waitFor(() => expect(screen.getByText("7 / 8")).toBeTruthy());
    expect(screen.getByText(/Today.s AI usage/)).toBeTruthy();
    expect(screen.queryByText(/larger daily allowance/i)).toBeNull();
  });

  it("signed in: shows the larger allowance", async () => {
    authRef.current = { user: { id: "u1" }, status: "authenticated" };
    getAiQuota.mockResolvedValue({
      enabled: true,
      tier: "authenticated",
      per_day: { limit: 40, used: 17, remaining: 23, resets_at: 0 },
      per_minute: { limit: 6, used: 0, remaining: 6, resets_at: 0 },
    });
    render(<AiAnchor context={{ activePage: "dashboard" } as ResearchContextEnvelope} />, { wrapper: Wrapper });
    openAnchorPanel();
    await waitFor(() => expect(screen.getByText("17 / 40")).toBeTruthy());
    expect(screen.queryByText(/larger daily allowance/i)).toBeNull();
  });

  it("renders nothing when the backend says limiting is disabled", async () => {
    getAiQuota.mockResolvedValue({ enabled: false, tier: "guest" });
    render(<AiAnchor context={{ activePage: "dashboard" } as ResearchContextEnvelope} />, { wrapper: Wrapper });
    openAnchorPanel();
    await waitFor(() => expect(getAiQuota).toHaveBeenCalled());
    expect(screen.queryByText(/Today.s AI usage/)).toBeNull();
  });
});
