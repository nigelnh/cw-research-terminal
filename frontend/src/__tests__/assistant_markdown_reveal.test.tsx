// @vitest-environment happy-dom
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantMarkdown } from "@/features/ai_assistant/assistant_markdown";

afterEach(cleanup);

describe("AssistantMarkdown — font + word-by-word reveal", () => {
  it("renders in the composer's mono font, not the display font", () => {
    const { container } = render(<AssistantMarkdown>plain text</AssistantMarkdown>);
    expect(container.firstElementChild?.className).toContain("mono");
  });

  it("a settled (non-streaming) message shows the full text instantly", () => {
    const { getByText } = render(
      <AssistantMarkdown streaming={false}>HPG closed up on volume.</AssistantMarkdown>,
    );
    expect(getByText("HPG closed up on volume.")).toBeTruthy();
  });

  it("a streaming message reveals word-by-word, reaching the full text quickly", () => {
    vi.useFakeTimers();
    try {
      const text = "HPG closed the session up one percent on steady volume today.";
      const { container } = render(<AssistantMarkdown streaming>{text}</AssistantMarkdown>);
      // nothing has had a chance to reveal yet
      expect(container.textContent).toBe("");
      act(() => vi.advanceTimersByTime(30));
      const afterOneTick = container.textContent || "";
      expect(afterOneTick.length).toBeGreaterThan(0);
      expect(afterOneTick.length).toBeLessThan(text.length); // still catching up, not a jump-to-end
      act(() => vi.advanceTimersByTime(2000)); // well past what a ~10-word reply needs
      expect(container.textContent?.trim()).toBe(text);
    } finally {
      vi.useRealTimers();
    }
  });

  it("switching from streaming to settled snaps immediately to the full text", () => {
    vi.useFakeTimers();
    try {
      const text = "A fairly long sentence with quite a few words to reveal gradually over time.";
      const { container, rerender } = render(<AssistantMarkdown streaming>{text}</AssistantMarkdown>);
      act(() => vi.advanceTimersByTime(30)); // partial reveal, deliberately not caught up
      expect(container.textContent?.trim()).not.toBe(text);
      rerender(<AssistantMarkdown streaming={false}>{text}</AssistantMarkdown>);
      expect(container.textContent?.trim()).toBe(text);
    } finally {
      vi.useRealTimers();
    }
  });
});
