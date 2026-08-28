import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import {
  type StoredChatMessage,
  type CopilotHistoryStore,
  loadCopilotHistory,
  saveCopilotHistory,
  createEmptyConversation,
  generateConversationTitle,
  generateId,
  COPILOT_STORAGE_KEY_V2,
  LEGACY_STORAGE_KEY_V1,
} from "./copilot_history_store";

export interface ChatMessage {
  id?: string;
  role: "user" | "assistant" | "system";
  content: string;
  createdAt?: number;
}

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
  moneyness?: number | null;
  moneynessLabel?: string | null;
  delta?: number | null;
  gamma?: number | null;
  theta?: number | null;
  vega?: number | null;
}

export interface ResearchContextEnvelope {
  activePage: "dashboard" | "research";
  selectedInstrument?: SelectedInstrumentContext | null;
  watchlist?: string[];
  realtimeStatus?: string;
  dataMode?: string;
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

export function useAiChat(apiEndpoint: string = "/api/ai/chat") {
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

        const response = await fetch(apiEndpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            messages: outboundMessages,
            context: context || null,
            stream: true,
          }),
          signal: abortControllerRef.current.signal,
        });

        if (!response.ok) {
          if (response.status === 429) {
            throw new Error("Rate limit reached. Please wait a moment and try again.");
          } else if (response.status === 503) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || "AI assistant is temporarily unavailable.");
          } else if (response.status === 502) {
            throw new Error("AI provider authentication failed.");
          } else {
            throw new Error("Failed to generate AI response.");
          }
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

            const jsonStr = trimmedLine.slice(6);
            try {
              const data = JSON.parse(jsonStr);
              if (data.error) {
                throw new Error(data.error);
              }
              if (data.type === "activity" && data.label) {
                setActivity(data.label);
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
            } catch (err: any) {
              if (err.message && err.message !== "Unexpected end of JSON input") {
                throw err;
              }
            }
          }
        }

        // Finalize plain text and persist completed assistant message
        const normalized = normalizePlainResponse(accumulatedText);
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
                content: normalized || accumulatedText,
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
        const errorMsg = err.message || "An unexpected error occurred.";
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
