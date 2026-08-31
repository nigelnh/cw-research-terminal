import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Orbit, Plus, History, Minus } from "lucide-react";
import { useAiChatContext } from "@/data/ai/ai_chat_provider";
import { normalizePlainResponse } from "@/data/ai/use_ai_chat";
import { formatRelativeTime } from "@/data/ai/copilot_history_store";
import { getActivityLabel } from "./ai_repl_bar";

const POS_KEY = "cw_research:ai_anchor_pos:v1";
const ANCHOR = 34; // px, square
const EDGE = 16; // safe inset
const PANEL_W = 380;
const PANEL_H = 460;
const DRAG_THRESHOLD = 4;

interface Pos {
  x: number;
  y: number;
}

function clampToViewport(p: Pos): Pos {
  const maxX = Math.max(EDGE, window.innerWidth - ANCHOR - EDGE);
  const maxY = Math.max(EDGE, window.innerHeight - ANCHOR - EDGE);
  return { x: Math.min(Math.max(p.x, EDGE), maxX), y: Math.min(Math.max(p.y, EDGE), maxY) };
}

function defaultPos(): Pos {
  return clampToViewport({
    x: window.innerWidth - ANCHOR - EDGE,
    y: window.innerHeight - ANCHOR - EDGE - 4,
  });
}

function loadPos(): Pos {
  try {
    const raw = window.localStorage?.getItem(POS_KEY);
    if (raw) {
      const p = JSON.parse(raw);
      if (typeof p?.x === "number" && typeof p?.y === "number") return clampToViewport(p);
    }
  } catch {
    /* ignore */
  }
  return defaultPos();
}

function savePos(p: Pos) {
  try {
    window.localStorage?.setItem(POS_KEY, JSON.stringify(p));
  } catch {
    /* ignore */
  }
}

/** Where the panel opens relative to the anchor, based on which quadrant it sits in. */
function panelBox(anchor: Pos) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const w = Math.min(PANEL_W, vw - 2 * EDGE);
  const h = Math.min(PANEL_H, vh - 2 * EDGE - ANCHOR);
  const openLeft = anchor.x + ANCHOR / 2 > vw / 2;
  const openUp = anchor.y + ANCHOR / 2 > vh / 2;
  let left = openLeft ? anchor.x + ANCHOR - w : anchor.x;
  let top = openUp ? anchor.y - h - 8 : anchor.y + ANCHOR + 8;
  left = Math.min(Math.max(left, EDGE), vw - w - EDGE);
  top = Math.min(Math.max(top, EDGE), vh - h - EDGE);
  return { left, top, w, h, openLeft, openUp };
}

export function AiAnchor() {
  const chat = useAiChatContext();
  const {
    messages,
    conversations,
    activeConversationId,
    isLoading,
    activity,
    error,
    startNewConversation,
    selectConversation,
  } = chat;

  const [pos, setPos] = useState<Pos>(() =>
    typeof window === "undefined" ? { x: 0, y: 0 } : loadPos(),
  );
  const [open, setOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const dragState = useRef<{ dx: number; dy: number; ox: number; oy: number; moved: boolean } | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);

  const streaming = isLoading && messages[messages.length - 1]?.role !== "assistant";
  const lastUser = [...messages].reverse().find((m) => m.role === "user")?.content;

  // keep anchor on-screen through viewport resize
  useEffect(() => {
    const onResize = () => setPos((p) => clampToViewport(p));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // scroll the conversation to the newest message as it streams (without stealing focus)
  useLayoutEffect(() => {
    if (open && bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [open, messages, activity]);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (e.button !== 0) return;
      (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
      dragState.current = {
        dx: e.clientX - pos.x,
        dy: e.clientY - pos.y,
        ox: e.clientX,
        oy: e.clientY,
        moved: false,
      };
    },
    [pos],
  );

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    const st = dragState.current;
    if (!st) return;
    if (!st.moved) {
      if (Math.hypot(e.clientX - st.ox, e.clientY - st.oy) <= DRAG_THRESHOLD) return;
      st.moved = true;
      setDragging(true);
    }
    setPos(clampToViewport({ x: e.clientX - st.dx, y: e.clientY - st.dy }));
  }, []);

  const onPointerUp = useCallback(
    (e: React.PointerEvent) => {
      const st = dragState.current;
      dragState.current = null;
      (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
      if (st?.moved) {
        setDragging(false);
        setPos((p) => {
          const c = clampToViewport(p);
          savePos(c);
          return c;
        });
      } else {
        // a click, not a drag -> toggle the panel
        setOpen((o) => !o);
      }
    },
    [],
  );

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setOpen((o) => !o);
    } else if (e.key === "Escape" && open) {
      setOpen(false);
    }
  };

  if (typeof document === "undefined") return null;

  const box = panelBox(pos);
  const dotState = error ? "var(--down)" : streaming ? "var(--accent-violet)" : "var(--accent)";

  const node = (
    <>
      {open && (
        <div
          role="dialog"
          aria-label="Research assistant conversation"
          style={{
            position: "fixed",
            left: box.left,
            top: box.top,
            width: box.w,
            height: box.h,
            background: "var(--panel)",
            border: "1px solid var(--border-strong)",
            boxShadow: "0 12px 40px rgba(0,0,0,0.45)",
            display: "flex",
            flexDirection: "column",
            zIndex: 90,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "7px 10px",
              borderBottom: "1px solid var(--border)",
              flexShrink: 0,
            }}
          >
            <Orbit size={13} strokeWidth={1.6} color="var(--accent)" />
            <span className="heading" style={{ fontSize: 11, letterSpacing: "0.04em", color: "var(--t-80)" }}>
              RESEARCH ASSISTANT
            </span>
            <span style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
              <button
                type="button"
                onClick={() => startNewConversation()}
                title="New chat"
                aria-label="New chat"
                style={iconBtn}
              >
                <Plus size={13} strokeWidth={1.8} />
              </button>
              <button
                type="button"
                onClick={() => setHistoryOpen((o) => !o)}
                title="Chat history"
                aria-label="Chat history"
                style={{ ...iconBtn, color: historyOpen ? "var(--accent)" : "var(--t-50)" }}
              >
                <History size={13} strokeWidth={1.8} />
              </button>
              <button
                type="button"
                onClick={() => setOpen(false)}
                title="Minimize"
                aria-label="Minimize conversation"
                style={iconBtn}
              >
                <Minus size={13} strokeWidth={1.8} />
              </button>
            </span>
          </div>

          {historyOpen && (
            <div
              className="mono"
              style={{
                maxHeight: 150,
                overflowY: "auto",
                borderBottom: "1px solid var(--border)",
                padding: "6px 10px",
                flexShrink: 0,
              }}
            >
              {conversations.length === 0 ? (
                <div style={{ fontSize: 11, color: "var(--t-46)", padding: "6px 0" }}>No previous conversations.</div>
              ) : (
                conversations.map((c) => (
                  <div
                    key={c.id}
                    onClick={() => {
                      selectConversation(c.id);
                      setHistoryOpen(false);
                    }}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 8,
                      padding: "4px 4px",
                      cursor: "pointer",
                      fontSize: 10.5,
                      color: c.id === activeConversationId ? "var(--accent)" : "var(--t-70)",
                    }}
                  >
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.title}</span>
                    <span style={{ color: "var(--t-46)", flexShrink: 0 }}>{formatRelativeTime(c.updatedAt)}</span>
                  </div>
                ))
              )}
            </div>
          )}

          <div
            ref={bodyRef}
            className="mono"
            style={{
              flex: 1,
              minHeight: 0,
              overflowY: "auto",
              padding: "10px 12px",
              fontSize: 11.5,
              lineHeight: 1.55,
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            {messages.length === 0 && !streaming && (
              <div style={{ color: "var(--t-46)", fontSize: 11 }}>
                Ask about pricing, greeks, contract terms, disclosures or corporate events. Grounded on the
                selected instrument.
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} style={{ whiteSpace: "pre-wrap", color: m.role === "user" ? "var(--accent)" : "var(--t-85)" }}>
                {m.role === "user" ? "> " : ""}
                {m.role === "assistant" ? normalizePlainResponse(m.content) : m.content}
              </div>
            ))}
            {streaming && (
              <div style={{ color: "var(--t-55)", fontStyle: "italic" }}>
                {activity || getActivityLabel(lastUser, undefined)}
              </div>
            )}
            {error && <div style={{ color: "var(--down)" }}>{error}</div>}
          </div>
        </div>
      )}

      <button
        type="button"
        aria-label={open ? "Close research assistant" : "Open research assistant"}
        aria-expanded={open}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onKeyDown={onKeyDown}
        className="focus-ring"
        style={{
          position: "fixed",
          left: pos.x,
          top: pos.y,
          width: ANCHOR,
          height: ANCHOR,
          borderRadius: 3,
          border: "1px solid var(--border-strong)",
          background: "var(--panel-2)",
          color: "var(--t-80)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          cursor: dragging ? "grabbing" : "grab",
          zIndex: 91,
          touchAction: "none",
          boxShadow: open ? "0 0 0 1px var(--accent)" : "0 2px 10px rgba(0,0,0,0.35)",
          transition: dragging ? "none" : "box-shadow 120ms ease",
        }}
      >
        <Orbit size={16} strokeWidth={1.5} />
        <span
          aria-hidden
          style={{
            position: "absolute",
            right: 3,
            top: 3,
            width: 5,
            height: 5,
            borderRadius: "50%",
            background: dotState,
          }}
        />
      </button>
    </>
  );

  return createPortal(node, document.body);
}

const iconBtn: React.CSSProperties = {
  background: "none",
  border: "none",
  cursor: "pointer",
  color: "var(--t-50)",
  padding: 2,
  display: "flex",
  alignItems: "center",
};
