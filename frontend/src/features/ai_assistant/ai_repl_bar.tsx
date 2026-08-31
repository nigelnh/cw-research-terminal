import { useEffect, useRef, useState } from "react";
import { Plus, History, Paperclip } from "lucide-react";
import { useAiChatContext } from "@/data/ai/ai_chat_provider";
import { type ResearchContextEnvelope } from "@/data/ai/use_ai_chat";
import { formatRelativeTime } from "@/data/ai/copilot_history_store";

interface AiReplBarProps {
  context?: ResearchContextEnvelope;
}

/** Short "what the assistant is doing" label shown while a response streams. */
export function getActivityLabel(lastUserText?: string, activeSymbol?: string): string {
  const text = (lastUserText || "").toUpperCase();
  if (activeSymbol) {
    return activeSymbol.startsWith("C")
      ? `Reviewing ${activeSymbol} analytics…`
      : `Checking ${activeSymbol} data…`;
  }
  if (text.includes("DIVIDEND") || text.includes("CORPORATE") || text.includes("EVENT") || text.includes("DISCLOS")) {
    return "Reading disclosures & events…";
  }
  if (text.includes("IV") || text.includes("VOLATILITY") || text.includes("HV")) {
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
  if (text.includes("VALUATION") || text.includes("FAIR") || text.includes("THEO")) {
    return "Calculating valuation metrics…";
  }
  return "Preparing response…";
}

const ICON_BTN: React.CSSProperties = {
  background: "none",
  border: "none",
  cursor: "pointer",
  color: "var(--t-50)",
  padding: 2,
  display: "flex",
  alignItems: "center",
};

/**
 * Docked REPL input at the bottom of the instrument panel. Typing lives here; the
 * assistant's replies render in the floating draggable conversation panel (`AiAnchor`).
 * Both read the same `useAiChat` via `AiChatProvider`.
 */
export function AiReplBar({ context }: AiReplBarProps) {
  const {
    conversations,
    activeConversationId,
    isLoading,
    sendMessage,
    startNewConversation,
    selectConversation,
    setLatestContext,
  } = useAiChatContext();

  const [input, setInput] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [attachment, setAttachment] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  // keep the shared context current so the floating panel grounds on the same selection
  useEffect(() => {
    setLatestContext(context);
  }, [context, setLatestContext]);

  useEffect(() => {
    if (!historyOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setHistoryOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [historyOpen]);

  const submit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!input.trim() || isLoading) return;
    const text = input;
    setInput("");
    setHistoryOpen(false);
    sendMessage(text, context);
  };

  return (
    <div style={{ borderTop: "1px solid var(--border)", flexShrink: 0 }}>
      {historyOpen && (
        <div
          className="mono"
          style={{
            maxHeight: 160,
            overflowY: "auto",
            padding: "8px 20px",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          <div style={{ fontSize: 9.5, letterSpacing: "0.06em", color: "var(--t-46)", marginBottom: 4 }}>
            CONVERSATIONS
          </div>
          {conversations.length === 0 ? (
            <div style={{ fontSize: 11, color: "var(--t-46)", padding: "8px 0" }}>No previous conversations.</div>
          ) : (
            conversations.map((conv) => {
              const active = conv.id === activeConversationId;
              return (
                <div
                  key={conv.id}
                  onClick={() => {
                    selectConversation(conv.id);
                    setHistoryOpen(false);
                  }}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 8,
                    padding: "5px 6px",
                    cursor: "pointer",
                    fontSize: 11,
                    background: active ? "var(--panel-3)" : "transparent",
                    color: active ? "var(--accent)" : "var(--t-70)",
                  }}
                >
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={conv.title}>
                    {conv.title}
                  </span>
                  <span style={{ color: "var(--t-46)", flexShrink: 0 }}>{formatRelativeTime(conv.updatedAt)}</span>
                </div>
              );
            })
          )}
        </div>
      )}

      {attachment && (
        <div style={{ padding: "6px 20px 0 20px" }}>
          <span
            className="mono"
            title="Attachments not yet sent — pending backend support"
            style={{
              fontSize: 10.5,
              color: "var(--t-55)",
              border: "1px solid var(--border-26)",
              padding: "2px 8px",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            {attachment}
            <button
              type="button"
              onClick={() => setAttachment(null)}
              aria-label="Remove attachment"
              style={{ ...ICON_BTN, color: "var(--t-46)" }}
            >
              ×
            </button>
          </span>
        </div>
      )}

      <form onSubmit={submit} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 20px" }}>
        <span
          className="mono"
          style={{ color: "var(--accent-violet)", fontSize: 11.5, lineHeight: 1, display: "flex", alignItems: "center" }}
        >
          &gt;
        </span>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="ask about pricing, greeks, contract terms, disclosures or events…"
          aria-label="Ask the research assistant"
          style={{
            flex: 1,
            background: "transparent",
            border: "none",
            outline: "none",
            boxShadow: "none",
            fontFamily: "var(--font-mono)",
            fontSize: 11.5,
            color: "var(--t-92)",
          }}
        />
        <button
          type="button"
          onClick={() => {
            startNewConversation();
            setHistoryOpen(false);
          }}
          title="New chat"
          aria-label="New chat"
          style={{ ...ICON_BTN, fontSize: 14 }}
        >
          <Plus size={13} strokeWidth={1.8} />
        </button>
        <button
          type="button"
          onClick={() => setHistoryOpen((o) => !o)}
          title="Chat history"
          aria-label="Chat history"
          style={{ ...ICON_BTN, color: historyOpen ? "var(--accent)" : "var(--t-50)" }}
        >
          <History size={13} strokeWidth={1.8} />
        </button>
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          title="Attach files (.xlsx, .pdf, .docx, .txt, images) — not yet sent, pending backend support"
          aria-label="Attach file"
          style={ICON_BTN}
        >
          <Paperclip size={13} strokeWidth={1.8} />
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".xlsx,.pdf,.docx,.txt,image/*"
          hidden
          onChange={(e) => setAttachment(e.target.files?.[0]?.name ?? null)}
        />
      </form>
    </div>
  );
}
