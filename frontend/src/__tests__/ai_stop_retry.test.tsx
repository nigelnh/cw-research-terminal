// @vitest-environment happy-dom
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import { renderHook, act, waitFor, cleanup } from "@testing-library/react";
import { useAiChat, CHAT_STORAGE_KEY } from "@/data/ai/use_ai_chat";
beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("Retry resends the frozen question/context without duplicating the user turn", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Try again" }), {
        status: 503,
        headers: { "content-type": "application/json" },
      }),
    )
    .mockResolvedValueOnce(
      new Response('data: {"content":"Recovered answer"}\n\ndata: [DONE]\n\n'),
    );
  vi.stubGlobal("fetch", fetcher);
  const { result } = renderHook(() => useAiChat("http://fixture/ai"));
  const context = {
    activePage: "dashboard" as const,
    selectedInstrument: { symbol: "HPG" },
  };
  await act(() => result.current.sendMessage("Explain this contract", context));
  context.selectedInstrument.symbol = "VPB";
  expect(result.current.canRetry).toBe(true);
  await act(() => result.current.retry());
  const sent = JSON.parse(fetcher.mock.calls[1][1].body);
  expect(sent.context.selectedInstrument.symbol).toBe("HPG");
  expect(sent.messages.filter((m: any) => m.role === "user")).toHaveLength(1);
  expect(result.current.messages.filter((m) => m.role === "user")).toHaveLength(
    1,
  );
  expect(
    result.current.messages[result.current.messages.length - 1]?.content,
  ).toBe("Recovered answer");
});

it("Stop saves partial text and late completion cannot clear a newer request", async () => {
  let stream: ReadableStreamDefaultController<Uint8Array>;
  const first = new ReadableStream<Uint8Array>({
    start(c) {
      stream = c;
    },
  });
  const second = new ReadableStream<Uint8Array>({
    start(c) {
      c.enqueue(new TextEncoder().encode('data: {"content":"New answer"}\n\n'));
      c.close();
    },
  });
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(new Response(first))
      .mockResolvedValueOnce(new Response(second)),
  );
  const { result } = renderHook(() => useAiChat("http://fixture/ai"));
  let pending: Promise<void>;
  act(() => {
    pending = result.current.sendMessage("First");
  });
  await act(async () => {
    stream.enqueue(
      new TextEncoder().encode('data: {"content":"Partial answer"}\n\n'),
    );
  });
  await waitFor(() =>
    expect(
      result.current.messages[result.current.messages.length - 1]?.content,
    ).toBe("Partial answer"),
  );
  act(() => result.current.stop());
  expect(result.current.isLoading).toBe(false);
  expect(result.current.activity).toBeNull();
  expect(result.current.stopped).toBe(true);
  expect(window.localStorage.getItem(CHAT_STORAGE_KEY)).toContain(
    "Partial answer",
  );
  await act(() => result.current.sendMessage("Second"));
  await act(async () => {
    stream.enqueue(new TextEncoder().encode('data: {"content":" late"}\n\n'));
    await pending;
  });
  expect(
    result.current.messages.find((m) => m.content === "Partial answer"),
  ).toBeTruthy();
  expect(
    result.current.messages[result.current.messages.length - 1]?.content,
  ).toBe("New answer");
});
