import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { config } from "@/config";
import {
  type StoredChatMessage,
  type TraceStep,
  type CopilotHistoryStore,
  loadCopilotHistory,
  saveCopilotHistory,
  createEmptyConversation,
  generateConversationTitle,
  generateId,
  COPILOT_STORAGE_KEY_V2,
  LEGACY_STORAGE_KEY_V1,
} from "./copilot_history_store";

/**
 * The AI chat endpoint on the configured backend. In production this is the absolute
 * Railway URL (from VITE_MARKET_DATA_REST_URL, same origin the market REST + WS use); in
 * local dev it is http://localhost:8501. A bare "/api/ai/chat" would resolve against the
 * Vercel static origin, which has no such route (POST -> 405) - that was the production bug.
 */
export const DEFAULT_AI_CHAT_ENDPOINT = `${(config.apiUrl || "").replace(/\/$/, "")}/api/ai/chat`;

/**
 * Internal AI failure codes emitted by the backend (`X-AI-Error-Code` header on a non-2xx
 * response, or a `code` field on an SSE `{error}` frame). Kept in the console for support;
 * the user only ever sees the short prose the backend already sanitised.
 */
export type AiErrorCode =
  | "AI_DISABLED"
  | "AI_BUDGET_EXCEEDED"
  | "RATE_LIMITED"
  | "MODEL_UNAVAILABLE"
  | "UPSTREAM_AUTH_ERROR"
  | "UPSTREAM_TIMEOUT"
  | "UPSTREAM_RATE_LIMIT"
  | "UPSTREAM_ERROR"
  | "INVALID_REQUEST"
  | "STREAM_INTERRUPTED"
  | "NETWORK_ERROR"
  | "INTERNAL_ERROR";

const AI_ERROR_FALLBACK_MESSAGE: Record<AiErrorCode, string> = {
  AI_DISABLED: "The AI research assistant is turned off on this server.",
  AI_BUDGET_EXCEEDED:
    "The AI assistant has reached its daily usage limit. Try again tomorrow.",
  RATE_LIMITED: "The AI assistant is busy right now. Please retry in a moment.",
  MODEL_UNAVAILABLE:
    "The AI model is temporarily unavailable. Please try again shortly.",
  UPSTREAM_AUTH_ERROR:
    "The AI service is unavailable (provider authentication).",
  UPSTREAM_TIMEOUT: "The AI response timed out. Please try again.",
  UPSTREAM_RATE_LIMIT:
    "The AI provider is rate-limiting requests. Please retry in a moment.",
  UPSTREAM_ERROR: "The AI service returned an error. Please try again.",
  INVALID_REQUEST: "That request could not be processed.",
  STREAM_INTERRUPTED: "The AI response was interrupted. Please try again.",
  NETWORK_ERROR: "Could not reach the AI service. Please try again.",
  INTERNAL_ERROR:
    "An unexpected error occurred while generating the AI response.",
};

function messageForAiError(
  code: string | null | undefined,
  serverMessage?: string,
): string {
  if (serverMessage && serverMessage.trim()) return serverMessage.trim();
  if (code && code in AI_ERROR_FALLBACK_MESSAGE) {
    return AI_ERROR_FALLBACK_MESSAGE[code as AiErrorCode];
  }
  return "Failed to generate AI response.";
}

export interface ChatMessage {
  id?: string;
  role: "user" | "assistant" | "system";
  content: string;
  createdAt?: number;
  trace?: TraceStep[];
}

export type { TraceStep };

export interface SelectedInstrumentContext {
  symbol: string;
  instrumentType?: string;
  issuer?: string | null;
  underlyingSymbol?: string | null;
  strikePrice?: number | null;
  exerciseRatio?: number | null;
  maturityDate?: string | null;
  lastTradingDate?: string | null;
  dte?: string | null;
  underlyingPrice?: number | null;
  bidPrice?: number | null;
  askPrice?: number | null;
  lastPrice?: number | null;
  priceChangePercent?: number | null;
  spread?: number | null;
  spreadPercent?: number | null;
  volume?: number | null;
  ivBid?: number | null;
  ivTrade?: number | null;
  ivAsk?: number | null;
  /** Canonical S/K from the backend quant engine (null if the quant gate rejected the contract). */
  moneyness?: number | null;
  /** Canonical ITM | ATM | OTM label from the backend (null when moneyness is null). */
  moneynessLabel?: string | null;
  /** Backend contract-lifecycle state: ACTIVE | NEAR_EXPIRY | LAST_TRADING_DAY | PENDING_MATURITY | EXPIRED. */
  contractState?: string | null;
  /** True when the backend quant engine returned live IV/greeks for this instrument. */
  quantAvailable?: boolean;
  delta?: number | null;
  gamma?: number | null;
  theta?: number | null;
  vega?: number | null;
}

export interface ResearchContextEnvelope {
  activePage: "dashboard" | "research" | "news";
  selectedInstrument?: SelectedInstrumentContext | null;
  watchlist?: string[];
  realtimeStatus?: string;
  dataMode?: string;
  marketSession?: string;
  marketSessionActive?: boolean;
  quoteDisplayEligible?: boolean;
  /** Step 13C temporal context. */
  dataState?: string; // LIVE | LAST_SESSION | MIXED | UNAVAILABLE
  quoteAsOf?: string | null; // ISO instant / session date the selected quote is from
  latestCompletedSession?: string | null;
  calendarConfidence?: string | null;
}

export { COPILOT_STORAGE_KEY_V2, LEGACY_STORAGE_KEY_V1 };
export const CHAT_STORAGE_KEY = COPILOT_STORAGE_KEY_V2;

/**
 * Normalizes assistant response text by removing stray Markdown syntax
 * (bold asterisks, headings, bullet markers) while preserving paragraph breaks and mathematical notation.
 */
export function normalizePlainResponse(text: string): string {
  if (!text) return "";
  return (
    text
      // Strip markdown bold markers **text** -> text
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      // Strip markdown bold markers __text__ -> text
      .replace(/__([^_]+)__/g, "$1")
      // Strip markdown header hashes # Header -> Header
      .replace(/^#{1,6}\s+/gm, "")
      // Strip bullet markers at line start: "- " or "* " -> ""
      .replace(/^[\*\-]\s+/gm, "")
      .trim()
  );
}

interface ChatRequest {
  conversationId: string;
  assistantId: string;
  messages: ChatMessage[];
  context: ResearchContextEnvelope | null;
}

export function useAiChat(apiEndpoint: string = DEFAULT_AI_CHAT_ENDPOINT) {
  const [store, setStore] = useState<CopilotHistoryStore>(() =>
    loadCopilotHistory(),
  );
  const storeRef = useRef(store);
  const [isLoading, setIsLoading] = useState(false);
  const [activity, setActivity] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stopped, setStopped] = useState(false);
  const [retryRequest, setRetryRequest] = useState<ChatRequest | null>(null);
  const running = useRef<{
    request: ChatRequest;
    controller: AbortController;
  } | null>(null);
  const update = useCallback(
    (fn: (s: CopilotHistoryStore) => CopilotHistoryStore, persist = true) => {
      const next = fn(storeRef.current);
      storeRef.current = next;
      setStore(next);
      if (persist) saveCopilotHistory(next);
    },
    [],
  );
  const activeConversation =
    store.conversations.find((c) => c.id === store.activeConversationId) ??
    store.conversations[0];
  const messages: ChatMessage[] = activeConversation?.messages ?? [];
  const conversations = useMemo(
    () => [...store.conversations].sort((a, b) => b.updatedAt - a.updatedAt),
    [store.conversations],
  );

  // Invalidating the run before abort prevents a late chunk/finally from altering a new turn.
  const cancel = useCallback((allowRetry: boolean) => {
    const run = running.current;
    running.current = null;
    run?.controller.abort();
    setIsLoading(false);
    setActivity(null);
    setError(null);
    setStopped(allowRetry && !!run);
    setRetryRequest(allowRetry && run ? run.request : null);
    saveCopilotHistory(storeRef.current);
  }, []);
  const stop = useCallback(() => cancel(true), [cancel]);
  useEffect(
    () => () => {
      running.current?.controller.abort();
      running.current = null;
    },
    [],
  );

  const startNewConversation = useCallback(() => {
    cancel(false);
    update((prev) => {
      const active = prev.conversations.find(
        (c) => c.id === prev.activeConversationId,
      );
      if (active?.messages.length === 0) return prev;
      const fresh = createEmptyConversation();
      return {
        version: 2,
        activeConversationId: fresh.id,
        conversations: [fresh, ...prev.conversations],
      };
    });
  }, [cancel, update]);
  const selectConversation = useCallback(
    (id: string) => {
      cancel(false);
      update((prev) =>
        prev.conversations.some((c) => c.id === id)
          ? { ...prev, activeConversationId: id }
          : prev,
      );
    },
    [cancel, update],
  );
  const deleteConversation = useCallback(
    (id: string) => {
      if (storeRef.current.activeConversationId === id) cancel(false);
      update((prev) => {
        const remaining = prev.conversations.filter((c) => c.id !== id);
        if (!remaining.length) remaining.push(createEmptyConversation());
        return {
          ...prev,
          conversations: remaining,
          activeConversationId:
            prev.activeConversationId === id
              ? remaining[0].id
              : prev.activeConversationId,
        };
      });
    },
    [cancel, update],
  );

  const execute = useCallback(
    async (request: ChatRequest) => {
      if (running.current) return;
      const run = { request, controller: new AbortController() };
      running.current = run;
      setIsLoading(true);
      setStopped(false);
      setError(null);
      setActivity(null);
      setRetryRequest(null);
      const patchAssistant = (
        fn: (m: StoredChatMessage) => StoredChatMessage,
      ) => {
        if (running.current !== run) return;
        update(
          (prev) => ({
            ...prev,
            conversations: prev.conversations.map((c) =>
              c.id !== request.conversationId
                ? c
                : {
                    ...c,
                    updatedAt: Date.now(),
                    messages: c.messages.map((m) =>
                      m.id === request.assistantId ? fn(m) : m,
                    ),
                  },
            ),
          }),
          false,
        );
      };
      try {
        const response = await fetch(apiEndpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            messages: request.messages,
            context: request.context,
            stream: true,
          }),
          signal: run.controller.signal,
        });
        if (running.current !== run) return;
        if (!response.ok) {
          const code =
            response.headers.get("X-AI-Error-Code") ??
            (response.status === 429
              ? "RATE_LIMITED"
              : response.status === 503
                ? "AI_DISABLED"
                : null);
          const data = await response.json().catch(() => ({}));
          throw new Error(messageForAiError(code, data.detail));
        }
        const reader = response.body?.getReader();
        if (!reader)
          throw new Error("Streaming is not supported by the browser.");
        const decoder = new TextDecoder();
        let buffer = "";
        const frame = (line: string) => {
          if (running.current !== run || !line.trim().startsWith("data:"))
            return;
          const raw = line.trim().slice(5).trim();
          if (!raw || raw === "[DONE]") return;
          let data;
          try {
            data = JSON.parse(raw);
          } catch {
            return;
          }
          if (data.error)
            throw new Error(messageForAiError(data.code, data.error));
          if (
            (data.type === "status" || data.type === "activity") &&
            data.label
          )
            setActivity(data.label);
          if (data.type === "tool_complete") {
            const step: TraceStep = {
              tool: data.tool,
              display_name: data.display_name,
              context: data.context,
              result_summary: data.result_summary,
              duration_ms: data.duration_ms,
              ok: data.ok !== false,
            };
            patchAssistant((m) => ({
              ...m,
              trace: [...(m.trace ?? []), step],
            }));
          }
          if (data.content)
            patchAssistant((m) => ({
              ...m,
              content: m.content + data.content,
            }));
        };
        try {
          while (running.current === run) {
            const { done, value } = await reader.read();
            if (running.current !== run) break;
            buffer += done
              ? decoder.decode()
              : decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";
            lines.forEach(frame);
            if (done) {
              frame(buffer);
              break;
            }
          }
        } finally {
          void reader.cancel().catch(() => {});
          reader.releaseLock();
        }
      } catch (err) {
        if (running.current !== run || run.controller.signal.aborted) return;
        setError(
          err instanceof TypeError
            ? AI_ERROR_FALLBACK_MESSAGE.NETWORK_ERROR
            : err instanceof Error
              ? err.message
              : "An unexpected error occurred.",
        );
        setRetryRequest(request);
        // Preserve partial output, but omit an empty failed placeholder from history.
        update((prev) => ({
          ...prev,
          conversations: prev.conversations.map((c) =>
            c.id !== request.conversationId
              ? c
              : {
                  ...c,
                  messages: c.messages.filter(
                    (m) =>
                      m.id !== request.assistantId ||
                      !!m.content ||
                      !!m.trace?.length,
                  ),
                },
          ),
        }));
      } finally {
        if (running.current === run) {
          running.current = null;
          setIsLoading(false);
          setActivity(null);
          saveCopilotHistory(storeRef.current);
        }
      }
    },
    [apiEndpoint, update],
  );

  const sendMessage = useCallback(
    async (input: string, context?: ResearchContextEnvelope) => {
      const text = input.trim();
      if (!text || running.current) return;
      const current = storeRef.current;
      const conversation =
        current.conversations.find(
          (c) => c.id === current.activeConversationId,
        ) ?? createEmptyConversation();
      const user: StoredChatMessage = {
        id: generateId("msg"),
        role: "user",
        content: text,
        createdAt: Date.now(),
      };
      const assistant: StoredChatMessage = {
        id: generateId("msg"),
        role: "assistant",
        content: "",
        createdAt: Date.now(),
      };
      const request: ChatRequest = {
        conversationId: conversation.id,
        assistantId: assistant.id,
        messages: [...conversation.messages, user],
        context: context ? JSON.parse(JSON.stringify(context)) : null,
      };
      update((prev) => ({
        version: 2,
        activeConversationId: conversation.id,
        conversations: [
          {
            ...conversation,
            title: conversation.messages.length
              ? conversation.title
              : generateConversationTitle(text),
            updatedAt: Date.now(),
            messages: [...conversation.messages, user, assistant],
          },
          ...prev.conversations.filter((c) => c.id !== conversation.id),
        ],
      }));
      await execute(request);
    },
    [execute, update],
  );
  const retry = useCallback(async () => {
    if (
      !retryRequest ||
      running.current ||
      retryRequest.conversationId !== storeRef.current.activeConversationId
    )
      return;
    const placeholder: StoredChatMessage = {
      id: retryRequest.assistantId,
      role: "assistant",
      content: "",
      createdAt: Date.now(),
    };
    update((prev) => ({
      ...prev,
      conversations: prev.conversations.map((c) =>
        c.id !== retryRequest.conversationId
          ? c
          : {
              ...c,
              messages: [
                ...c.messages.filter((m) => m.id !== retryRequest.assistantId),
                placeholder,
              ],
            },
      ),
    }));
    await execute(retryRequest);
  }, [retryRequest, execute, update]);

  return {
    messages,
    conversations,
    activeConversationId: store.activeConversationId,
    activeConversationTitle: activeConversation?.title ?? "New conversation",
    isLoading,
    activity,
    error,
    hasHydrated: true,
    sendMessage,
    startNewConversation,
    selectConversation,
    deleteConversation,
    clearMessages: startNewConversation,
    stop,
    retry,
    stopped,
    canRetry: !!retryRequest && !isLoading,
  };
}
