// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { render, fireEvent, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { AiChatProvider } from "@/data/ai/ai_chat_provider";
import { AiAnchor } from "@/features/ai_assistant/ai_anchor";

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
  return render(<AiAnchor />, { wrapper: Wrapper });
}

beforeEach(() => {
  window.localStorage.clear();
  window.innerWidth = 1440;
  window.innerHeight = 900;
});
afterEach(cleanup);

describe("AiAnchor — draggable assistant anchor + fixed conversation panel", () => {
  it("defaults to the bottom-right of the viewport with a safe inset", () => {
    const { getByRole } = renderAnchor();
    const btn = getByRole("button", { name: /open research assistant/i });
    // 1440x900, anchor 34, edge 16, repl-bar clearance 48
    // -> x = 1440-34-16 = 1390, y = 900-34-16-48 = 802
    expect(btn.style.left).toBe("1390px");
    expect(btn.style.top).toBe("802px");
    expect(btn.getAttribute("aria-expanded")).toBe("false");
  });

  it("a click (no drag) toggles the fixed-size conversation panel", () => {
    const { getByRole, queryByRole } = renderAnchor();
    const btn = getByRole("button", { name: /open research assistant/i });
    expect(queryByRole("dialog")).toBeNull();

    fireEvent.pointerDown(btn, { button: 0, clientX: 1390, clientY: 802, pointerId: 1 });
    fireEvent.pointerUp(btn, { clientX: 1390, clientY: 802, pointerId: 1 });

    const panel = getByRole("dialog", { name: /research assistant conversation/i });
    // fixed, bounded dimensions — never grows with content
    expect(panel.style.position).toBe("fixed");
    expect(panel.style.width).toBe("380px");
    expect(panel.style.height).toBe("460px");
    expect(getByRole("button", { name: /close research assistant/i })).toBeTruthy();
  });

  it("a drag past the threshold moves the anchor, persists it, and does NOT open the panel", () => {
    const { getByRole, queryByRole } = renderAnchor();
    const btn = getByRole("button", { name: /open research assistant/i });

    fireEvent.pointerDown(btn, { button: 0, clientX: 1390, clientY: 802, pointerId: 1 });
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
    fireEvent.pointerDown(btn, { button: 0, clientX: 1390, clientY: 802, pointerId: 1 });
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
});
