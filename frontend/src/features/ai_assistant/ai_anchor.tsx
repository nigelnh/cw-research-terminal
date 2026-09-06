import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Orbit, Plus, History, Minus, CornerDownLeft, AtSign, X } from "lucide-react";
import { useAiChatContext } from "@/data/ai/ai_chat_provider";
import type { ResearchContextEnvelope, TraceStep } from "@/data/ai/use_ai_chat";
import { formatRelativeTime } from "@/data/ai/copilot_history_store";
import { useAiQuota } from "@/data/ai/use_ai_quota";
import type { AiQuota } from "@/data/backend/backend_client";
import { AssistantMarkdown } from "./assistant_markdown";
import { ATTACHMENT_ACCEPT, useFileAttachments } from "@/data/ai/use_file_attachments";
import { prefersReducedMotion, spring } from "@/design/motion";

const POS_KEY = "cw_research:ai_anchor_pos:v1";
const DRAFT_KEY = "cw_research:ai_draft:v1";
const ANCHOR = 34; // px, square
const EDGE = 16; // safe viewport inset
const PANEL_W = 380;
const PANEL_H = 468;
const DRAG_THRESHOLD = 4;
const NEAR_BOTTOM_PX = 64;

/** Short, friendly empty-state prompts. One is picked per panel mount (see below). */
const EMPTY_PHRASES = [
  "What are we looking at?",
  "Ask me anything.",
  "What do you want to know?",
  "Need a second opinion?",
  "What are you researching?",
  "What's the question?",
];

interface Pos {
  x: number;
  y: number;
}

interface AiAnchorProps {
  /** Current page/instrument context, kept fresh so the conversation grounds on it. */
  context?: ResearchContextEnvelope;
}

function clampToViewport(p: Pos): Pos {
  const maxX = Math.max(EDGE, window.innerWidth - ANCHOR - EDGE);
  const maxY = Math.max(EDGE, window.innerHeight - ANCHOR - EDGE);
  return { x: Math.min(Math.max(p.x, EDGE), maxX), y: Math.min(Math.max(p.y, EDGE), maxY) };
}

function defaultPos(): Pos {
  return clampToViewport({
    x: window.innerWidth - ANCHOR - EDGE,
    y: window.innerHeight - ANCHOR - EDGE,
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
  return { left, top, w, h };
}

// ---------------------------------------------------------------- research trace
function stepGlyph(ok: boolean): string {
  return ok ? "✓" : "!"; // ✓ / !
}

function ResearchTrace({ steps, live, running }: { steps: TraceStep[]; live: string | null; running: boolean }) {
  const [open, setOpen] = useState(running);
  useEffect(() => {
    // keep it open while working; collapse once done (user can re-expand)
    setOpen(running);
  }, [running]);

  if (steps.length === 0 && !running) return null;

  const totalMs = steps.reduce((s, x) => s + (x.duration_ms ?? 0), 0);
  const dur = totalMs < 1000 ? `${totalMs} ms` : `${(totalMs / 1000).toFixed(1)}s`;
  const summary =
    steps.length > 0
      ? `Research trace · ${steps.length} tool${steps.length === 1 ? "" : "s"} · ${dur}`
      : "Working…";

  return (
    <div
      className="mono"
      style={{
        fontSize: 10,
        color: "var(--t-50)",
        border: "1px solid var(--border-26)",
        borderRadius: 2,
        padding: "5px 8px",
        background: "var(--panel-2)",
        display: "flex",
        flexDirection: "column",
        gap: 3,
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          background: "none",
          border: "none",
          padding: 0,
          textAlign: "left",
          cursor: "pointer",
          color: "var(--t-55)",
          fontFamily: "inherit",
          fontSize: 10,
        }}
      >
        {running ? "Working…" : `${open ? "▾" : "▸"} ${summary}`}
      </button>
      {(open || running) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 2, paddingTop: 2 }}>
          {steps.map((s, i) => (
            <div key={i} className={running ? "trace-step is-live" : "trace-step"} style={{ display: "flex", gap: 6, color: s.ok ? "var(--t-60)" : "var(--down)" }}>
              <span style={{ color: s.ok ? "var(--up)" : "var(--down)", width: 8, flexShrink: 0 }}>
                {stepGlyph(s.ok)}
              </span>
              <span style={{ overflow: "hidden" }}>
                {s.display_name}
                {s.context ? <span style={{ color: "var(--t-42)" }}> {"·"} {s.context}</span> : null}
                {s.result_summary ? (
                  <span style={{ color: "var(--t-46)" }}>
                    {" — "}
                    {s.result_summary}
                    {typeof s.duration_ms === "number" ? ` · ${s.duration_ms} ms` : ""}
                  </span>
                ) : null}
              </span>
            </div>
          ))}
          {running && (
            <div style={{ display: "flex", gap: 6, color: "var(--t-55)" }}>
              <span style={{ width: 8, flexShrink: 0 }}>{"•"}</span>
              <span>{live || "Synthesizing answer…"}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------- quota strip
/**
 * Today's AI-chat allowance, always in view (not a surprise 429). Renders nothing until
 * the backend confirms limiting is on and a daily window exists. A guest sees an upsell
 * to signing in; the bar turns amber near the ceiling.
 */
function QuotaStrip({ quota }: { quota: AiQuota | undefined }) {
  const fillRef = useRef<HTMLDivElement>(null);
  const wasNear = useRef(false);
  const day = quota?.enabled ? quota.per_day : null;

  const near = !!day && day.remaining <= Math.max(1, Math.ceil(day.limit * 0.15));
  // One pulse the frame the bar first crosses into the amber zone — not on every render.
  useEffect(() => {
    const el = fillRef.current;
    if (near && !wasNear.current && el && !prefersReducedMotion() && typeof el.animate === "function") {
      const { easing, duration } = spring("snap");
      el.animate([{ opacity: 0.45 }, { opacity: 1 }], { duration: duration + 120, easing });
    }
    wasNear.current = near;
  }, [near]);

  if (!day || !quota) return null;

  const pct = day.limit > 0 ? Math.min(100, Math.round((day.used / day.limit) * 100)) : 0;
  const bar = near ? "var(--warn)" : "var(--accent)";
  const settle = spring("settle");

  return (
    <div
      className="mono"
      style={{
        padding: "6px 12px 8px",
        borderTop: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        gap: 4,
        fontSize: 10,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", color: near ? "var(--warn)" : "var(--t-55)" }}>
        <span>Today&rsquo;s AI usage</span>
        <span style={{ fontVariantNumeric: "tabular-nums" }}>{day.used} / {day.limit}</span>
      </div>
      <div style={{ height: 2, background: "var(--border)", borderRadius: 1, overflow: "hidden" }}>
        <div
          ref={fillRef}
          style={{
            width: `${pct}%`,
            height: "100%",
            background: bar,
            transition: prefersReducedMotion() ? "none" : `width ${settle.duration}ms ${settle.easing}`,
          }}
        />
      </div>
      {quota.tier === "guest" && (
        <div style={{ color: "var(--t-46)", marginTop: 1 }}>
          Sign in for a larger daily allowance.
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------- composer
function Composer({
  onSend,
  disabled,
  draftKey,
  attachments,
}: {
  onSend: (text: string) => void;
  disabled: boolean;
  draftKey: string;
  attachments: ReturnType<typeof useFileAttachments>;
}) {
  const [value, setValue] = useState<string>(() => {
    try {
      return window.localStorage?.getItem(draftKey) ?? "";
    } catch {
      return "";
    }
  });
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [fileNotice, setFileNotice] = useState(false);

  useEffect(() => {
    try {
      if (value) window.localStorage?.setItem(draftKey, value);
      else window.localStorage?.removeItem(draftKey);
    } catch {
      /* ignore */
    }
  }, [value, draftKey]);

  const submit = () => {
    const text = value.trim();
    if (!text || disabled || attachments.reading) return;
    if (attachments.files.length) { setFileNotice(true); return; }
    setFileNotice(false);
    setValue("");
    try {
      window.localStorage?.removeItem(draftKey);
    } catch {
      /* ignore */
    }
    onSend(text);
  };

  return (
    <form onSubmit={(e) => { e.preventDefault(); submit(); }} className="ai-composer">
      {attachments.files.length > 0 && (
        <div className="ai-file-list">
          {attachments.files.map(file => (
            <div key={file.name} className="ai-file-chip">
              <span title={file.name}>{file.name}</span>
              <button type="button" aria-label={`Remove ${file.name}`} onClick={() => attachments.remove(file.name)} disabled={disabled}>
                <X size={11} />
              </button>
            </div>
          ))}
        </div>
      )}
      {attachments.reading && <div role="status" className="ai-file-feedback">Reading files…</div>}
      {attachments.error && (
        <div role="alert" className="ai-file-feedback" style={{ color: "var(--down)" }}>
          {attachments.error} {attachments.files.length > 0 && <button type="button" onClick={attachments.retry}>Retry reading</button>}
        </div>
      )}
      {attachments.previews.map(file => (
        <details key={file.name} className="ai-file-preview">
          <summary>Preview {file.name} · {file.characters.toLocaleString()} characters</summary>
          {file.warnings.map(warning => <p key={warning}>{warning}</p>)}
          <pre>{file.sections.map(section => `[${section.location}] ${section.text}`).join("\n").slice(0, 6000)}</pre>
          {file.characters > 6000 && <p>Preview shows the first 6,000 characters.</p>}
        </details>
      ))}
      {attachments.files.length > 0 && !attachments.reading && (
        <div role={fileNotice ? "status" : undefined} className="ai-file-feedback">
          File preview only. Sending file content to AI awaits approval.
        </div>
      )}
      <div className="ai-composer-input">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); }
          }}
          rows={2}
          placeholder="Ask about pricing, Greeks, contract terms, disclosures or events…"
          aria-label="Ask the research assistant"
        />
        <div className="ai-composer-actions">
          <input ref={fileInput} type="file" multiple accept={ATTACHMENT_ACCEPT} style={{ display: "none" }}
            aria-label="Upload research files"
            onChange={(e) => {
              const selected = Array.from(e.target.files || []);
              if (selected.length) attachments.add(selected);
              e.target.value = "";
            }} />
          <button type="button" aria-label="Upload files" title="Upload up to 2 files · 20 MB total · PDF, text, CSV, XLSX, DOCX"
            disabled={disabled || attachments.reading} onClick={() => fileInput.current?.click()}>
            <AtSign size={14} strokeWidth={1.8} />
          </button>
          <button type="submit" disabled={disabled || attachments.reading || !value.trim()}
            aria-label="Send" title="Send (Enter). Shift+Enter for a new line."
            style={{ color: value.trim() && !disabled ? "var(--accent)" : "var(--t-42)" }}>
            <CornerDownLeft size={14} strokeWidth={1.8} />
          </button>
        </div>
      </div>
    </form>
  );
}

// ------------------------------------------------------------------------ anchor
export function AiAnchor({ context }: AiAnchorProps) {
  const chat = useAiChatContext();
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
    setLatestContext,
  } = chat;

  const attachments = useFileAttachments(activeConversationId);
  const { quota, refresh: refreshQuota } = useAiQuota();

  const [pos, setPos] = useState<Pos>(() => (typeof window === "undefined" ? { x: 0, y: 0 } : loadPos()));
  const [open, setOpen] = useState(false);
  // Pick one empty-state phrase on mount; stays put across re-renders and messages.
  const [emptyPhrase] = useState(() => EMPTY_PHRASES[Math.floor(Math.random() * EMPTY_PHRASES.length)]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const dragState = useRef<{ dx: number; dy: number; ox: number; oy: number; moved: boolean } | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const nearBottomRef = useRef(true);

  // keep the shared context fresh for the conversation / any resend
  useEffect(() => {
    setLatestContext(context);
  }, [context, setLatestContext]);

  const lastMsg = messages[messages.length - 1];
  const streaming = isLoading && (!lastMsg || lastMsg.role !== "assistant" || !lastMsg.content);
  const assistantRunning = isLoading && lastMsg?.role === "assistant";
  const busy = streaming || assistantRunning;

  // keep anchor on-screen through viewport resize
  useEffect(() => {
    const onResize = () => setPos((p) => clampToViewport(p));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // auto-scroll to newest output ONLY if the user is already near the bottom
  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (!el || !open) return;
    if (nearBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [open, messages, activity]);

  const onBodyScroll = () => {
    const el = bodyRef.current;
    if (!el) return;
    nearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
  };

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (e.button !== 0) return;
      (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
      dragState.current = { dx: e.clientX - pos.x, dy: e.clientY - pos.y, ox: e.clientX, oy: e.clientY, moved: false };
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

  const onPointerUp = useCallback((e: React.PointerEvent) => {
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
      setOpen((o) => !o);
    }
  }, []);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setOpen((o) => !o);
    } else if (e.key === "Escape" && open) {
      setOpen(false);
    }
  };

  const send = useCallback(
    (text: string) => {
      nearBottomRef.current = true;
      sendMessage(text, context);
      // the rate-limit hit lands server-side almost immediately; give it a beat then re-read.
      window.setTimeout(refreshQuota, 900);
    },
    [sendMessage, context, refreshQuota],
  );

  // fresh count whenever the panel is opened
  useEffect(() => {
    if (open) refreshQuota();
  }, [open, refreshQuota]);

  const box = useMemo(() => panelBox(pos), [pos]);

  if (typeof document === "undefined") return null;

  const dotState = error ? "var(--down)" : streaming || assistantRunning ? "var(--accent-violet)" : "var(--accent)";

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
              <button type="button" onClick={() => startNewConversation()} title="New chat" aria-label="New chat" style={iconBtn}>
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
              <button type="button" onClick={() => setOpen(false)} title="Minimize" aria-label="Minimize conversation" style={iconBtn}>
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
            onScroll={onBodyScroll}
            style={{
              flex: 1,
              minHeight: 0,
              overflowY: "auto",
              padding: "10px 12px",
              display: "flex",
              flexDirection: "column",
              gap: 12,
            }}
          >
            {messages.length === 0 && !streaming && (
              <div
                className="heading ai-empty-prompt"
                style={{ color: "var(--t-46)", fontSize: 11, letterSpacing: "0.04em", textAlign: "center", margin: "auto" }}
              >
                {emptyPhrase}
              </div>
            )}

            {messages.map((m, i) => {
              const isLast = i === messages.length - 1;
              if (m.role === "user") {
                return (
                  <div
                    key={m.id ?? i}
                    className="mono"
                    style={{ whiteSpace: "pre-wrap", color: "var(--accent)", fontSize: 11.5, lineHeight: 1.5 }}
                  >
                    {"> "}
                    {m.content}
                  </div>
                );
              }
              const running = isLast && assistantRunning;
              return (
                <div key={m.id ?? i} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <ResearchTrace steps={m.trace ?? []} live={activity} running={running} />
                  {m.content ? (
                    <AssistantMarkdown streaming={running}>{m.content}</AssistantMarkdown>
                  ) : running && (m.trace?.length ?? 0) === 0 ? (
                    <div className="mono" style={{ color: "var(--t-55)", fontStyle: "italic", fontSize: 11 }}>
                      {activity || "Thinking…"}
                    </div>
                  ) : null}
                </div>
              );
            })}

            {streaming && messages.length > 0 && messages[messages.length - 1]?.role === "user" && (
              <div className="mono" style={{ color: "var(--t-55)", fontStyle: "italic", fontSize: 11 }}>
                {activity || "Thinking…"}
              </div>
            )}

            {error && (
              <div className="mono" style={{ color: "var(--down)", fontSize: 11, lineHeight: 1.5 }}>
                {error}
              </div>
            )}
          </div>

          <QuotaStrip quota={quota} />
          <Composer key={activeConversationId} onSend={send} disabled={isLoading} draftKey={DRAFT_KEY} attachments={attachments} />
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
          outline: "none",
          boxShadow: open ? "0 0 0 1px var(--accent)" : "0 2px 10px rgba(0,0,0,0.35)",
          transition: dragging ? "none" : "box-shadow 120ms ease",
        }}
      >
        <Orbit size={16} strokeWidth={1.5} className={busy ? "orbit-thinking" : undefined} />
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
