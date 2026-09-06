import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { config } from "@/config";
import { getAccessToken } from "@/data/backend/backend_client";
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
  AI_BUDGET_EXCEEDED: "The AI assistant has reached its daily usage limit. Try again tomorrow.",
  RATE_LIMITED: "The AI assistant is busy right now. Please retry in a moment.",
  MODEL_UNAVAILABLE: "The AI model is temporarily unavailable. Please try again shortly.",
  UPSTREAM_AUTH_ERROR: "The AI service is unavailable (provider authentication).",
  UPSTREAM_TIMEOUT: "The AI response timed out. Please try again.",
  UPSTREAM_RATE_LIMIT: "The AI provider is rate-limiting requests. Please retry in a moment.",
  UPSTREAM_ERROR: "The AI service returned an error. Please try again.",
  INVALID_REQUEST: "That request could not be processed.",
  STREAM_INTERRUPTED: "The AI response was interrupted. Please try again.",
  NETWORK_ERROR: "Could not reach the AI service. Please try again.",
  INTERNAL_ERROR: "An unexpected error occurred while generating the AI response.",
};

function messageForAiError(code: string | null | undefined, serverMessage?: string): string {
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
  dataState?: string;               // LIVE | LAST_SESSION | MIXED | UNAVAILABLE
  quoteAsOf?: string | null;        // ISO instant / session date the selected quote is from
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
  return text
    // Strip markdown bold markers **text** -> text
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    // Strip markdown bold markers __text__ -> text
    .replace(/__([^_]+)__/g, "$1")
    // Strip markdown header hashes # Header -> Header
    .replace(/^#{1,6}\s+/gm, "")
    // Strip bullet markers at line start: "- " or "* " -> ""
    .replace(/^[\*\-]\s+/gm, "")
    .trim();
}

export function useAiChat(
  apiEndpoint: string = DEFAULT_AI_CHAT_ENDPOINT,
  /** Verified auth subject, `null` for a guest, `undefined` while auth is still settling. */
  subject: string | null | undefined = undefined,
) {
  const [store, setStore] = useState<CopilotHistoryStore>(() => loadCopilotHistory());
  const [hasHydrated, setHasHydrated] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [activity, setActivity] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Synchronous hydration flag
  useEffect(() => {
    setHasHydrated(true);
  }, []);

  // Identity boundary: the auth provider has already wiped the local Copilot keys for the
  // new identity — drop the in-memory copy too so account A's conversations don't linger
  // in the panel until a reload. Adopts the first settled subject without resetting; a
  // token refresh (same subject) is a no-op.
  const knownSubject = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (subject === undefined) return;
    if (knownSubject.current === undefined) {
      knownSubject.current = subject;
      return;
    }
    if (knownSubject.current === subject) return;
    knownSubject.current = subject;
    abortControllerRef.current?.abort();
    setIsLoading(false);
    setError(null);
    setActivity(null);
    setStore(loadCopilotHistory());
  }, [subject]);

  // Compute active conversation
  const activeConversation = useMemo(() => {
    if (!store.activeConversationId) {
      return store.conversations[0] || null;
    }
    return store.conversations.find((c) => c.id === store.activeConversationId) || store.conversations[0] || null;
  }, [store]);

  // Messages of the active conversation
  const messages: ChatMessage[] = useMemo(() => {
    return activeConversation ? activeConversation.messages : [];
  }, [activeConversation]);

  // Conversations sorted by updatedAt descending
  const conversations = useMemo(() => {
    return [...store.conversations].sort((a, b) => b.updatedAt - a.updatedAt);
  }, [store.conversations]);

  /**
   * Starts a brand new conversation without removing previous conversations in history.
   */
  const startNewConversation = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setIsLoading(false);
    setError(null);

    const newConv = createEmptyConversation();
    setStore((prev) => {
      // If current active conversation is already empty with no messages, reuse it
      const currentActive = prev.conversations.find((c) => c.id === prev.activeConversationId);
      if (currentActive && currentActive.messages.length === 0) {
        return prev;
      }

      const nextStore: CopilotHistoryStore = {
        version: 2,
        activeConversationId: newConv.id,
        conversations: [newConv, ...prev.conversations],
      };
      saveCopilotHistory(nextStore);
      return nextStore;
    });
  }, []);

  /**
   * Switches to an existing conversation from history without re-sending AI requests.
   */
  const selectConversation = useCallback((convId: string) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setIsLoading(false);
    setError(null);

    setStore((prev) => {
      if (prev.activeConversationId === convId) return prev;
      const target = prev.conversations.find((c) => c.id === convId);
      if (!target) return prev;

      const nextStore: CopilotHistoryStore = {
        ...prev,
        activeConversationId: convId,
      };
      saveCopilotHistory(nextStore);
      return nextStore;
    });
  }, []);

  /**
   * Deletes a specific conversation from history.
   */
  const deleteConversation = useCallback((convId: string) => {
    setStore((prev) => {
      const filtered = prev.conversations.filter((c) => c.id !== convId);
      let nextActiveId = prev.activeConversationId;

      if (prev.activeConversationId === convId) {
        if (filtered.length > 0) {
          nextActiveId = filtered[0].id;
        } else {
          const fresh = createEmptyConversation();
          filtered.push(fresh);
          nextActiveId = fresh.id;
        }
      }

      const nextStore: CopilotHistoryStore = {
        version: 2,
        activeConversationId: nextActiveId,
        conversations: filtered,
      };
      saveCopilotHistory(nextStore);
      return nextStore;
    });
  }, []);

  /**
   * Resets/clears active conversation messages and restarts.
   */
  const clearMessages = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setError(null);
    setIsLoading(false);
    startNewConversation();
  }, [startNewConversation]);

  /**
   * Sends user message to AI and streams response into the active conversation.
   */
  const sendMessage = useCallback(
    async (userInput: string, context?: ResearchContextEnvelope) => {
      const trimmed = userInput.trim();
      if (!trimmed || isLoading) return;

      setError(null);
      const userMsgId = generateId("msg");
      const userMsg: StoredChatMessage = {
        id: userMsgId,
        role: "user",
        content: trimmed,
        createdAt: Date.now(),
      };

      const assistantMsgId = generateId("msg");
      const assistantPlaceholder: StoredChatMessage = {
        id: assistantMsgId,
        role: "assistant",
        content: "",
        createdAt: Date.now(),
      };

      // Target conversation ID
      let targetConvId = store.activeConversationId;
      if (!targetConvId || !store.conversations.some((c) => c.id === targetConvId)) {
        const fresh = createEmptyConversation();
        targetConvId = fresh.id;
      }

      // Update store with user message immediately (and generate title if first message)
      setStore((prev) => {
        let convs = [...prev.conversations];
        let convIndex = convs.findIndex((c) => c.id === targetConvId);

        if (convIndex === -1) {
          const fresh = createEmptyConversation();
          fresh.id = targetConvId!;
          convs.unshift(fresh);
          convIndex = 0;
        }

        const conv = convs[convIndex];
        const isFirstMessage = conv.messages.length === 0;
        const newTitle = isFirstMessage ? generateConversationTitle(trimmed) : conv.title;
        const updatedMsgs = [...conv.messages, userMsg, assistantPlaceholder];

        convs[convIndex] = {
          ...conv,
          title: newTitle,
          updatedAt: Date.now(),
          messages: updatedMsgs,
        };

        const nextStore: CopilotHistoryStore = {
          version: 2,
          activeConversationId: targetConvId,
          conversations: convs,
        };
        // Persist user message immediately
        saveCopilotHistory(nextStore);
        return nextStore;
      });

      setIsLoading(true);
      abortControllerRef.current = new AbortController();

      try {
        const outboundMessages = [
          ...(activeConversation?.messages || []),
          { role: "user", content: trimmed },
        ];

        // Attach the caller's bearer token when signed in, so the backend rate-limiter
        // keys this request to their account (authenticated allowance + visible quota)
        // instead of the shared per-IP guest bucket. Anonymous callers send no header.
        const token = await getAccessToken();
        const response = await fetch(apiEndpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            messages: outboundMessages,
            context: context || null,
            stream: true,
          }),
          signal: abortControllerRef.current.signal,
        });

        if (!response.ok) {
          // Prefer the backend's own classification; fall back to the HTTP status for
          // errors raised by upstream middleware (e.g. the shared rate limiter's 429).
          const code =
            response.headers.get("X-AI-Error-Code") ||
            (response.status === 429
              ? "RATE_LIMITED"
              : response.status === 503
                ? "AI_DISABLED"
                : response.status === 502
                  ? "UPSTREAM_ERROR"
                  : null);
          const errData = await response.json().catch(() => ({} as { detail?: string }));
          console.warn(`AI request failed [${code ?? "HTTP_" + response.status}] (HTTP ${response.status})`);
          throw new Error(messageForAiError(code, errData?.detail));
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error("Streaming is not supported by the browser.");
        }

        const decoder = new TextDecoder();
        let accumulatedText = "";
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            const trimmedLine = line.trim();
            if (!trimmedLine.startsWith("data: ")) continue;

            const jsonStr = trimmedLine.slice(6).trim();
            if (!jsonStr || jsonStr === "[DONE]") continue;

            try {
              const data = JSON.parse(jsonStr);
              if (data.error) {
                if (data.code) {
                  console.warn(`AI stream failed [${data.code}]`);
                }
                setError(messageForAiError(data.code, data.error));
                continue;
              }
              // --- research activity trace (sanitised; no reasoning/payloads) ---
              if (data.type === "status" && data.label) {
                setActivity(data.label);
              }
              if (data.type === "activity" && data.label) {
                // legacy frame — keep working
                setActivity(data.label);
              }
              if (data.type === "tool_complete") {
                const step: TraceStep = {
                  tool: data.tool,
                  display_name: data.display_name,
                  context: data.context,
                  result_summary: data.result_summary,
                  duration_ms: data.duration_ms,
                  ok: data.ok !== false,
                };
                setStore((prev) => {
                  const convs = [...prev.conversations];
                  const cIdx = convs.findIndex((c) => c.id === targetConvId);
                  if (cIdx === -1) return prev;
                  const conv = convs[cIdx];
                  const msgs = [...conv.messages];
                  const aIdx = msgs.findIndex((m) => m.id === assistantMsgId);
                  if (aIdx === -1) return prev;
                  const prevTrace = msgs[aIdx].trace ?? [];
                  msgs[aIdx] = { ...msgs[aIdx], trace: [...prevTrace, step] };
                  convs[cIdx] = { ...conv, messages: msgs };
                  return { ...prev, conversations: convs };
                });
              }
              if (data.content) {
                accumulatedText += data.content;
                setStore((prev) => {
                  const convs = [...prev.conversations];
                  const cIdx = convs.findIndex((c) => c.id === targetConvId);
                  if (cIdx !== -1) {
                    const conv = convs[cIdx];
                    const msgs = [...conv.messages];
                    const aIdx = msgs.findIndex((m) => m.id === assistantMsgId);
                    if (aIdx !== -1) {
                      msgs[aIdx] = { ...msgs[aIdx], content: accumulatedText };
                    }
                    convs[cIdx] = { ...conv, messages: msgs };
                    return { ...prev, conversations: convs };
                  }
                  return prev;
                });
              }
            } catch (err) {
              // Non-fatal: individual chunk decode anomaly should not kill the full stream
              console.warn("Failed to parse AI SSE chunk:", jsonStr, err);
            }
          }
        }

        // Persist the completed assistant message. Content is kept as raw Markdown —
        // the panel renders it (react-markdown). Only guard against a totally empty turn.
        setStore((prev) => {
          const convs = [...prev.conversations];
          const cIdx = convs.findIndex((c) => c.id === targetConvId);
          if (cIdx !== -1) {
            const conv = convs[cIdx];
            const msgs = [...conv.messages];
            const aIdx = msgs.findIndex((m) => m.id === assistantMsgId);
            if (aIdx !== -1) {
              msgs[aIdx] = {
                ...msgs[aIdx],
                content: accumulatedText,
              };
            }
            convs[cIdx] = {
              ...conv,
              updatedAt: Date.now(),
              messages: msgs,
            };
            const nextStore = { ...prev, conversations: convs };
            saveCopilotHistory(nextStore);
            return nextStore;
          }
          return prev;
        });
      } catch (err: any) {
        if (err.name === "AbortError") {
          return;
        }
        // A thrown TypeError here is the browser failing to reach the backend at all
        // (DNS, CORS preflight, offline) - distinct from a classified backend error.
        const isTransport = err instanceof TypeError;
        if (isTransport) {
          console.warn("AI request failed [NETWORK_ERROR]", err?.message);
        }
        const errorMsg = isTransport
          ? AI_ERROR_FALLBACK_MESSAGE.NETWORK_ERROR
          : err.message || "An unexpected error occurred.";
        setError(errorMsg);

        // Remove empty assistant placeholder if failed before receiving content
        setStore((prev) => {
          const convs = [...prev.conversations];
          const cIdx = convs.findIndex((c) => c.id === targetConvId);
          if (cIdx !== -1) {
            const conv = convs[cIdx];
            const msgs = conv.messages.filter((m) => m.id !== assistantMsgId || (m.content && m.content.trim().length > 0));
            convs[cIdx] = { ...conv, messages: msgs };
            const nextStore = { ...prev, conversations: convs };
            saveCopilotHistory(nextStore);
            return nextStore;
          }
          return prev;
        });
      } finally {
        setIsLoading(false);
        setActivity(null);
        abortControllerRef.current = null;
      }
    },
    [store, activeConversation, isLoading, apiEndpoint]
  );

  return {
    messages,
    conversations,
    activeConversationId: store.activeConversationId,
    activeConversationTitle: activeConversation?.title || "New conversation",
    isLoading,
    activity,
    error,
    hasHydrated,
    sendMessage,
    startNewConversation,
    selectConversation,
    deleteConversation,
    clearMessages,
  };
}
