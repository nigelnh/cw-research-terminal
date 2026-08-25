import { useState, useCallback, useRef } from "react";

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
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

export function useAiChat(apiEndpoint: string = "/api/ai/chat") {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const clearMessages = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setMessages([]);
    setError(null);
    setIsLoading(false);
  }, []);

  const sendMessage = useCallback(
    async (userInput: string, context?: ResearchContextEnvelope) => {
      const trimmed = userInput.trim();
      if (!trimmed || isLoading) return;

      setError(null);
      const userMessage: ChatMessage = { role: "user", content: trimmed };
      const updatedMessages = [...messages, userMessage];
      setMessages(updatedMessages);
      setIsLoading(true);

      // Create placeholder assistant message for streaming
      const assistantMessageIndex = updatedMessages.length;
      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      abortControllerRef.current = new AbortController();

      try {
        const response = await fetch(apiEndpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            messages: updatedMessages,
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
              if (data.content) {
                accumulatedText += data.content;
                setMessages((prev) => {
                  const copy = [...prev];
                  if (copy[assistantMessageIndex]) {
                    copy[assistantMessageIndex] = {
                      role: "assistant",
                      content: accumulatedText,
                    };
                  }
                  return copy;
                });
              }
            } catch (err: any) {
              if (err.message && err.message !== "Unexpected end of JSON input") {
                throw err;
              }
            }
          }
        }
      } catch (err: any) {
        if (err.name === "AbortError") {
          return;
        }
        const errorMsg = err.message || "An unexpected error occurred.";
        setError(errorMsg);
        // Remove empty assistant placeholder if failed completely
        setMessages((prev) => {
          const copy = [...prev];
          if (copy[assistantMessageIndex] && !copy[assistantMessageIndex].content) {
            copy.splice(assistantMessageIndex, 1);
          }
          return copy;
        });
      } finally {
        setIsLoading(false);
        abortControllerRef.current = null;
      }
    },
    [messages, isLoading, apiEndpoint]
  );

  return {
    messages,
    isLoading,
    error,
    sendMessage,
    clearMessages,
  };
}
