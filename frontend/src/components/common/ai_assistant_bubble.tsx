import React, { useState, useEffect, useRef } from "react";
import { Sparkles, X, RotateCcw, ArrowUp } from "lucide-react";
import { useAiChat, type ResearchContextEnvelope } from "@/data/ai/use_ai_chat";

const STORAGE_KEY = "cw-assistant-bubble-pos:v1";

interface Position {
  x: number; // offset from right in px
  y: number; // offset from bottom in px
}

interface AiAssistantBubbleProps {
  context?: ResearchContextEnvelope;
}

export function AiAssistantBubble({ context }: AiAssistantBubbleProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [inputText, setInputText] = useState("");
  const { messages, isLoading, error, sendMessage, clearMessages } = useAiChat();
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const [position, setPosition] = useState<Position>(() => {
    if (typeof window !== "undefined" && window.localStorage) {
      try {
        const saved = window.localStorage.getItem(STORAGE_KEY);
        if (saved) {
          const parsed = JSON.parse(saved);
          if (typeof parsed.x === "number" && typeof parsed.y === "number") {
            return parsed;
          }
        }
      } catch {
        // Fallback
      }
    }
    return { x: 28, y: 28 };
  });

  const isDragging = useRef(false);
  const startCoord = useRef<{ startX: number; startY: number; posX: number; posY: number }>({
    startX: 0,
    startY: 0,
    posX: 28,
    posY: 28,
  });
  const hasMoved = useRef(false);

  const handleMouseDown = (e: React.MouseEvent) => {
    isDragging.current = true;
    hasMoved.current = false;
    startCoord.current = {
      startX: e.clientX,
      startY: e.clientY,
      posX: position.x,
      posY: position.y,
    };
  };

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return;
      const dx = startCoord.current.startX - e.clientX;
      const dy = startCoord.current.startY - e.clientY;

      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) {
        hasMoved.current = true;
      }

      const maxX = (window.innerWidth || 1200) - 60;
      const maxY = (window.innerHeight || 800) - 60;

      const newX = Math.max(16, Math.min(maxX, startCoord.current.posX + dx));
      const newY = Math.max(16, Math.min(maxY, startCoord.current.posY + dy));

      setPosition({ x: newX, y: newY });
    };

    const handleMouseUp = () => {
      if (isDragging.current) {
        isDragging.current = false;
        if (typeof window !== "undefined" && window.localStorage) {
          try {
            window.localStorage.setItem(STORAGE_KEY, JSON.stringify(position));
          } catch {
            // Ignore
          }
        }
      }
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [position]);

  // Scroll to bottom of message list on new messages
  useEffect(() => {
    if (isOpen && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, isOpen]);

  const handleClick = () => {
    if (!hasMoved.current) {
      setIsOpen((prev) => !prev);
    }
  };

  const handleSend = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!inputText.trim() || isLoading) return;
    const text = inputText;
    setInputText("");
    sendMessage(text, context);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const openBelow = typeof window !== "undefined" && position.y > (window.innerHeight || 800) - 460;
  const activeSymbol = context?.selectedInstrument?.symbol;
  const activeUnd = context?.selectedInstrument?.underlyingSymbol;

  return (
    <>
      {/* Floating Research Copilot Panel */}
      {isOpen && (
        <div
          role="region"
          aria-label="AI Research Assistant"
          style={{
            position: "fixed",
            right: `${position.x}px`,
            ...(openBelow
              ? { top: `${(typeof window !== "undefined" ? window.innerHeight : 800) - position.y + 10}px` }
              : { bottom: `${position.y + 46}px` }),
            width: "380px",
            maxWidth: "92vw",
            height: "480px",
            maxHeight: "80vh",
            backgroundColor: "var(--surface)",
            border: "1px solid var(--border-strong)",
            borderRadius: "6px",
            boxShadow: "0 16px 40px rgba(0, 0, 0, 0.7)",
            zIndex: 45,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
          }}
        >
          {/* Header */}
          <header
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "10px 14px",
              borderBottom: "1px solid var(--border)",
              backgroundColor: "var(--surface)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <Sparkles size={14} className="text-primary" />
              <span style={{ fontSize: "12px", fontWeight: 500, color: "var(--foreground)" }}>
                Research Copilot
              </span>
              {activeSymbol && (
                <span
                  className="tnum text-primary"
                  style={{
                    fontSize: "11px",
                    padding: "1px 6px",
                    borderRadius: "3px",
                    backgroundColor: "rgba(212, 232, 250, 0.1)",
                    border: "1px solid var(--border-strong)",
                  }}
                  title={`Active context: ${activeSymbol} (Underlying ${activeUnd || "—"})`}
                >
                  {activeSymbol}
                </span>
              )}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
              {messages.length > 0 && (
                <button
                  onClick={clearMessages}
                  className="focus-ring"
                  title="Clear conversation"
                  aria-label="Clear conversation"
                  style={{
                    background: "transparent",
                    border: "none",
                    color: "var(--subtle-foreground)",
                    cursor: "pointer",
                    padding: "4px",
                    borderRadius: "3px",
                    display: "flex",
                    alignItems: "center",
                  }}
                >
                  <RotateCcw size={13} />
                </button>
              )}
              <button
                onClick={() => setIsOpen(false)}
                className="focus-ring"
                title="Close Assistant"
                aria-label="Close Assistant"
                style={{
                  background: "transparent",
                  border: "none",
                  color: "var(--subtle-foreground)",
                  cursor: "pointer",
                  padding: "4px",
                  borderRadius: "3px",
                  display: "flex",
                  alignItems: "center",
                }}
              >
                <X size={14} />
              </button>
            </div>
          </header>

          {/* Conversation Message List */}
          <div
            style={{
              flex: 1,
              overflowY: "auto",
              padding: "14px",
              display: "flex",
              flexDirection: "column",
              gap: "12px",
              fontSize: "12px",
            }}
          >
            {messages.length === 0 ? (
              <div style={{ margin: "auto 0", textAlign: "center", color: "var(--subtle-foreground)", padding: "16px 8px" }}>
                <p style={{ fontSize: "13px", fontWeight: 500, color: "var(--muted-foreground)", marginBottom: "6px" }}>
                  CW Quantitative Copilot
                </p>
                <p style={{ fontSize: "11px", lineHeight: "1.5" }}>
                  {activeSymbol ? (
                    <>Ask about <strong className="text-primary">{activeSymbol}</strong> spread, moneyness, or volatility skew.</>
                  ) : (
                    <>Ask questions about covered warrant pricing, Greeks, or monitored watchlist items.</>
                  )}
                </p>
              </div>
            ) : (
              messages.map((m, i) => (
                <div
                  key={i}
                  style={{
                    alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                    maxWidth: "88%",
                    padding: m.role === "user" ? "8px 12px" : "8px 0",
                    borderRadius: "4px",
                    backgroundColor: m.role === "user" ? "rgba(255, 255, 255, 0.06)" : "transparent",
                    color: m.role === "user" ? "var(--foreground)" : "var(--foreground)",
                    fontSize: "12px",
                    lineHeight: "1.5",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {m.role === "assistant" && (
                    <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "4px", fontSize: "10px", color: "var(--subtle-foreground)" }}>
                      <span style={{ width: "4px", height: "4px", borderRadius: "50%", backgroundColor: "var(--primary)" }} />
                      Copilot
                    </div>
                  )}
                  {m.content || (isLoading && i === messages.length - 1 ? (
                    <span className="text-subtle">Analyzing context...</span>
                  ) : null)}
                </div>
              ))
            )}

            {error && (
              <div
                style={{
                  padding: "8px 10px",
                  borderRadius: "4px",
                  backgroundColor: "rgba(239, 68, 68, 0.1)",
                  border: "1px solid rgba(239, 68, 68, 0.25)",
                  color: "var(--destructive)",
                  fontSize: "11px",
                }}
              >
                {error}
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input Footer */}
          <form
            onSubmit={handleSend}
            style={{
              padding: "10px 12px",
              borderTop: "1px solid var(--border)",
              backgroundColor: "var(--surface)",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "flex-end",
                gap: "6px",
                backgroundColor: "rgba(255, 255, 255, 0.04)",
                border: "1px solid var(--border)",
                borderRadius: "4px",
                padding: "6px 8px",
              }}
            >
              <textarea
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={activeSymbol ? `Ask about ${activeSymbol}...` : "Ask about warrant pricing or Greeks..."}
                rows={1}
                className="focus-ring"
                style={{
                  flex: 1,
                  background: "transparent",
                  border: "none",
                  outline: "none",
                  resize: "none",
                  fontSize: "12px",
                  color: "var(--foreground)",
                  fontFamily: "inherit",
                  maxHeight: "80px",
                }}
              />
              <button
                type="submit"
                disabled={!inputText.trim() || isLoading}
                className="focus-ring"
                aria-label="Send message"
                style={{
                  background: inputText.trim() && !isLoading ? "var(--primary)" : "transparent",
                  color: inputText.trim() && !isLoading ? "var(--primary-foreground)" : "var(--subtle-foreground)",
                  border: "none",
                  borderRadius: "3px",
                  padding: "4px",
                  cursor: inputText.trim() && !isLoading ? "pointer" : "default",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  transition: "all 0.15s ease",
                }}
              >
                <ArrowUp size={14} strokeWidth={2} />
              </button>
            </div>
            <p style={{ marginTop: "6px", fontSize: "10px", color: "var(--subtle-foreground)", textAlign: "center" }}>
              AI responses generated via third-party inference.
            </p>
          </form>
        </div>
      )}

      {/* Draggable Trigger Bubble */}
      <button
        onMouseDown={handleMouseDown}
        onClick={handleClick}
        title="Open Research Assistant (drag to reposition)"
        aria-label="Open AI Research Assistant"
        className="focus-ring"
        style={{
          position: "fixed",
          right: `${position.x}px`,
          bottom: `${position.y}px`,
          width: "38px",
          height: "38px",
          borderRadius: "50%",
          backgroundColor: "var(--surface)",
          border: `1px solid ${isOpen ? "var(--primary)" : "var(--border-strong)"}`,
          boxShadow: "0 4px 16px rgba(0, 0, 0, 0.4)",
          color: "var(--primary)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          cursor: isDragging.current ? "grabbing" : "grab",
          zIndex: 45,
          userSelect: "none",
          transition: isDragging.current ? "none" : "border-color 0.15s ease",
        }}
      >
        <Sparkles size={16} strokeWidth={1.5} />
      </button>
    </>
  );
}
