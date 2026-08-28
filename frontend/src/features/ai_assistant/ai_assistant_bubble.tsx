import React, { useState, useEffect, useRef } from "react";
import { Sparkles, X, Plus, History, Trash2, ArrowUp } from "lucide-react";
import { useAiChat, normalizePlainResponse, type ResearchContextEnvelope } from "@/data/ai/use_ai_chat";
import { formatRelativeTime } from "@/data/ai/copilot_history_store";

export function getActivityLabel(lastUserText?: string, activeSymbol?: string): string {
  const text = (lastUserText || "").toUpperCase();
  if (text.includes("CVHM") || text.includes("CHPG")) return "Reviewing warrant analytics…";
  if (text.includes("HPG")) return "Checking HPG data…";
  if (text.includes("NVL")) return "Checking NVL data…";
  if (text.includes("VHM")) return "Checking VHM data…";
  if (activeSymbol) {
    return activeSymbol.startsWith("C")
      ? `Reviewing ${activeSymbol} analytics…`
      : `Checking ${activeSymbol} data…`;
  }
  if (
    text.includes("IV") ||
    text.includes("VOLATILITY") ||
    text.includes("BIẾN ĐỘNG") ||
    text.includes("HV")
  ) {
    return "Comparing volatility metrics…";
  }
  if (
    text.includes("GREEK") ||
    text.includes("DELTA") ||
    text.includes("GAMMA") ||
    text.includes("THETA") ||
    text.includes("VEGA")
  ) {
    return "Calculating Greek sensitivities…";
  }
  if (
    text.includes("VALUATION") ||
    text.includes("P/E") ||
    text.includes("ĐỊNH GIÁ") ||
    text.includes("FAIR") ||
    text.includes("THEO")
  ) {
    return "Calculating valuation metrics…";
  }
  return "Preparing response…";
}

const STORAGE_KEY = "cw-assistant-bubble-pos:v1";

interface Position {
  x: number; // offset from right in px
  y: number; // offset from bottom in px
}

interface AiAssistantBubbleProps {
  context?: ResearchContextEnvelope;
  initialOpen?: boolean;
}

export function AiAssistantBubble({ context, initialOpen = false }: AiAssistantBubbleProps) {
  const [isOpen, setIsOpen] = useState(initialOpen);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [inputText, setInputText] = useState("");
  const {
    messages,
    conversations,
    activeConversationId,
    isLoading,
    activity,
    error,
    sendMessage,
    startNewConversation,
    selectConversation,
    deleteConversation,
  } = useAiChat();
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
    if (isOpen && !isHistoryOpen && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, isOpen, isHistoryOpen]);

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
    setIsHistoryOpen(false);
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
            <div style={{ display: "flex", alignItems: "center", gap: "8px", minWidth: 0 }}>
              <Sparkles size={14} className="text-primary" />
              <span style={{ fontSize: "12px", fontWeight: 500, color: "var(--foreground)", whiteSpace: "nowrap" }}>
                Research Assistant
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
                    whiteSpace: "nowrap",
                  }}
                  title={`Active context: ${activeSymbol} (Underlying ${activeUnd || "—"})`}
                >
                  {activeSymbol}
                </span>
              )}
            </div>

            {/* Header Controls: [New Chat] [History] [Close] */}
            <div style={{ display: "flex", alignItems: "center", gap: "4px", flexShrink: 0 }}>
              <button
                onClick={() => {
                  startNewConversation();
                  setIsHistoryOpen(false);
                }}
                className="focus-ring"
                title="New conversation"
                aria-label="New conversation"
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
                <Plus size={14} />
              </button>

              <button
                onClick={() => setIsHistoryOpen((prev) => !prev)}
                className="focus-ring"
                title="Chat history"
                aria-label="Open chat history"
                style={{
                  background: isHistoryOpen ? "rgba(212, 232, 250, 0.12)" : "transparent",
                  border: "none",
                  color: isHistoryOpen ? "var(--primary)" : "var(--subtle-foreground)",
                  cursor: "pointer",
                  padding: "4px",
                  borderRadius: "3px",
                  display: "flex",
                  alignItems: "center",
                }}
              >
                <History size={14} />
              </button>

              <button
                onClick={() => {
                  setIsOpen(false);
                  setIsHistoryOpen(false);
                }}
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

          {/* Body: Either History View OR Conversation Messages */}
          {isHistoryOpen ? (
            <div
              style={{
                flex: 1,
                overflowY: "auto",
                padding: "12px",
                display: "flex",
                flexDirection: "column",
                gap: "6px",
                backgroundColor: "var(--surface)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "4px 6px 8px 6px",
                  borderBottom: "1px solid var(--border)",
                  marginBottom: "6px",
                }}
              >
                <span style={{ fontSize: "12px", fontWeight: 500, color: "var(--foreground)" }}>
                  Previous Conversations
                </span>
                {/* <span className="tnum" style={{ fontSize: "11px", color: "var(--subtle-foreground)" }}>
                  {conversations.length} saved
                </span> */}
              </div>

              {conversations.length === 0 ? (
                <div style={{ padding: "32px 0", textAlign: "center", fontSize: "12px", color: "var(--subtle-foreground)" }}>
                  No previous conversations.
                </div>
              ) : (
                conversations.map((conv) => {
                  const isActive = conv.id === activeConversationId;
                  return (
                    <div
                      key={conv.id}
                      onClick={() => {
                        selectConversation(conv.id);
                        setIsHistoryOpen(false);
                      }}
                      className={`table-row ${isActive ? "table-row-selected" : ""}`}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        padding: "8px 10px",
                        borderRadius: "4px",
                        cursor: "pointer",
                        backgroundColor: isActive ? "rgba(212, 232, 250, 0.06)" : "rgba(255, 255, 255, 0.02)",
                        border: "1px solid var(--border)",
                      }}
                    >
                      <div style={{ flex: 1, minWidth: 0, paddingRight: "8px" }}>
                        <div
                          style={{
                            fontSize: "12px",
                            fontWeight: isActive ? 500 : 400,
                            color: isActive ? "var(--primary)" : "var(--foreground)",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                          title={conv.title}
                        >
                          {conv.title}
                        </div>
                        <div
                          className="tnum"
                          style={{
                            fontSize: "11px",
                            color: "var(--subtle-foreground)",
                            marginTop: "2px",
                          }}
                        >
                          {formatRelativeTime(conv.updatedAt)} · {conv.messages.length} msgs
                        </div>
                      </div>

                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          deleteConversation(conv.id);
                        }}
                        title="Delete conversation"
                        aria-label={`Delete conversation ${conv.title}`}
                        style={{
                          background: "transparent",
                          border: "none",
                          color: "var(--subtle-foreground)",
                          cursor: "pointer",
                          padding: "4px",
                          borderRadius: "3px",
                          display: "flex",
                          alignItems: "center",
                          flexShrink: 0,
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.color = "var(--destructive)")}
                        onMouseLeave={(e) => (e.currentTarget.style.color = "var(--subtle-foreground)")}
                      >
                        <Trash2 size={12} strokeWidth={1.5} />
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          ) : (
            <div
              style={{
                flex: 1,
                overflowY: "auto",
                padding: "16px",
                display: "flex",
                flexDirection: "column",
                gap: "14px",
                fontSize: "13px",
              }}
            >
              {messages.length === 0 ? (
                <div style={{ margin: "auto 0", textAlign: "center", color: "var(--subtle-foreground)", padding: "16px 8px" }}>
                  <p style={{ fontSize: "12px", lineHeight: "1.5" }}>
                    {activeSymbol ? (
                      <>Ask about <strong className="text-primary">{activeSymbol}</strong> spread, moneyness, or volatility skew.</>
                    ) : (
                      <>Ask questions about covered warrant pricing, Greeks, or monitored watchlist items.</>
                    )}
                  </p>
                </div>
              ) : (
                messages.map((m, i) => {
                  if (m.role === "user") {
                    return (
                      <div
                        key={m.id || i}
                        style={{
                          alignSelf: "flex-end",
                          maxWidth: "85%",
                          padding: "8px 12px",
                          borderRadius: "6px",
                          backgroundColor: "rgba(255, 255, 255, 0.08)",
                          color: "var(--foreground)",
                          fontSize: "13px",
                          lineHeight: "1.5",
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                        }}
                      >
                        {m.content}
                      </div>
                    );
                  }

                  // Assistant response: Plain professional text without repeated labels or decorative icons
                  const isCurrentInFlight = isLoading && i === messages.length - 1;
                  const displayText = m.content ? normalizePlainResponse(m.content) : "";

                  return (
                    <div
                      key={m.id || i}
                      style={{
                        alignSelf: "flex-start",
                        maxWidth: "96%",
                        padding: "2px 0",
                        color: "var(--foreground)",
                        fontSize: "13px",
                        lineHeight: "1.6",
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                      }}
                    >
                      {displayText ? (
                        displayText
                      ) : isCurrentInFlight ? (
                        <span style={{ color: "var(--muted-foreground)", fontSize: "12px", fontStyle: "italic" }}>
                          {activity || getActivityLabel(messages[i - 1]?.content, activeSymbol)}
                        </span>
                      ) : null}
                    </div>
                  );
                })
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
          )}

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
                alignItems: "center",
                gap: "8px",
                height: "40px",
                backgroundColor: "rgba(255, 255, 255, 0.04)",
                border: "1px solid var(--border)",
                borderRadius: "4px",
                padding: "0 8px 0 10px",
                outline: "none",
                boxShadow: "none",
              }}
            >
              <textarea
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={activeSymbol ? `Ask about ${activeSymbol}...` : "Ask about warrant pricing or Greeks..."}
                rows={1}
                style={{
                  flex: 1,
                  height: "20px",
                  lineHeight: "20px",
                  background: "transparent",
                  border: "none",
                  outline: "none",
                  boxShadow: "none",
                  resize: "none",
                  fontSize: "12px",
                  color: "var(--foreground)",
                  fontFamily: "inherit",
                  padding: 0,
                  margin: 0,
                  display: "block",
                  overflow: "hidden",
                }}
              />
              <button
                type="submit"
                disabled={!inputText.trim() || isLoading}
                aria-label="Send message"
                style={{
                  width: "26px",
                  height: "26px",
                  flexShrink: 0,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  background: inputText.trim() && !isLoading ? "var(--primary)" : "transparent",
                  color: inputText.trim() && !isLoading ? "var(--primary-foreground)" : "var(--subtle-foreground)",
                  border: "none",
                  outline: "none",
                  boxShadow: "none",
                  borderRadius: "3px",
                  padding: 0,
                  margin: 0,
                  cursor: inputText.trim() && !isLoading ? "pointer" : "default",
                  transition: "all 0.15s ease",
                }}
              >
                <ArrowUp size={14} strokeWidth={2} />
              </button>
            </div>
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
