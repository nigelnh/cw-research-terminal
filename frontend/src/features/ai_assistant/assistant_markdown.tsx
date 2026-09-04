import { memo, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

/**
 * Grid Terminal-styled Markdown for assistant messages. Compact, restrained spacing,
 * IBM Plex Mono throughout (same face as the composer input), headings distinguishable
 * but small, tables scroll inside the ~360px panel. Renders partial Markdown cleanly
 * while a response streams.
 */

const H_BASE: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontWeight: 700,
  letterSpacing: "0.02em",
  color: "var(--t-92)",
  margin: "12px 0 4px",
  lineHeight: 1.3,
};

const WORDS_PER_SEC = 30;
const TICK_MS = 30;
const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Splits into "word + any trailing whitespace" tokens; rejoining a prefix reproduces an
 * exact (possibly truncated) substring, so partial reveals never mangle markdown spacing. */
function tokenizeWords(text: string): string[] {
  return text.match(/\S+\s*/g) ?? [];
}

/**
 * Reveals `text` word-by-word at a fast, steady pace while `active`, instead of popping in
 * whatever bursts the token stream happens to deliver. Falls further behind -> catches up
 * faster, so a burst never leaves a multi-second tail and the *total* time to fully reveal
 * stays close to when the last token actually arrived. Settled/historical messages (and
 * anyone with `prefers-reduced-motion`) render instantly, unpaced.
 */
function useWordReveal(text: string, active: boolean): string {
  const paced = active && !prefersReducedMotion();
  const [revealed, setRevealed] = useState(paced ? "" : text);
  const textRef = useRef(text);
  const revealedCountRef = useRef(paced ? 0 : tokenizeWords(text).length);

  // Track the latest text without restarting the reveal loop below; when inactive, keep
  // the displayed text exactly in sync (also covers the "just finished streaming" snap).
  useEffect(() => {
    textRef.current = text;
    if (!paced) {
      revealedCountRef.current = tokenizeWords(text).length;
      setRevealed(text);
    }
  }, [text, paced]);

  // The reveal loop itself only (re)starts when streaming turns on/off, not on every
  // chunk - it always reads the latest text/position via refs.
  useEffect(() => {
    if (!paced) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const step = () => {
      if (cancelled) return;
      const words = tokenizeWords(textRef.current);
      if (revealedCountRef.current < words.length) {
        const backlog = words.length - revealedCountRef.current;
        const rate = backlog > 12 ? WORDS_PER_SEC * 4 : backlog > 4 ? WORDS_PER_SEC * 2 : WORDS_PER_SEC;
        const advance = Math.max(1, Math.round((rate * TICK_MS) / 1000));
        revealedCountRef.current = Math.min(words.length, revealedCountRef.current + advance);
        setRevealed(words.slice(0, revealedCountRef.current).join(""));
      }
      timer = setTimeout(step, TICK_MS);
    };
    timer = setTimeout(step, TICK_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [paced]);

  return revealed;
}

const COMPONENTS: Components = {
  h1: ({ node, ...p }) => <div style={{ ...H_BASE, fontSize: 13 }} {...p} />,
  h2: ({ node, ...p }) => <div style={{ ...H_BASE, fontSize: 12 }} {...p} />,
  h3: ({ node, ...p }) => <div style={{ ...H_BASE, fontSize: 11.5 }} {...p} />,
  h4: ({ node, ...p }) => <div style={{ ...H_BASE, fontSize: 11 }} {...p} />,
  h5: ({ node, ...p }) => <div style={{ ...H_BASE, fontSize: 11 }} {...p} />,
  h6: ({ node, ...p }) => <div style={{ ...H_BASE, fontSize: 11 }} {...p} />,
  p: ({ node, ...p }) => <p style={{ margin: "4px 0", lineHeight: 1.55 }} {...p} />,
  ul: ({ node, ...p }) => (
    <ul style={{ margin: "4px 0", paddingLeft: 16, display: "flex", flexDirection: "column", gap: 2 }} {...p} />
  ),
  ol: ({ node, ...p }) => (
    <ol style={{ margin: "4px 0", paddingLeft: 18, display: "flex", flexDirection: "column", gap: 2 }} {...p} />
  ),
  li: ({ node, ...p }) => <li style={{ lineHeight: 1.5 }} {...p} />,
  strong: ({ node, ...p }) => <strong style={{ color: "var(--t-92)", fontWeight: 700 }} {...p} />,
  em: ({ node, ...p }) => <em style={{ color: "var(--t-70)" }} {...p} />,
  a: ({ node, ...p }) => (
    <a
      target="_blank"
      rel="noopener noreferrer"
      style={{ color: "var(--accent)", textDecoration: "underline", textUnderlineOffset: 2 }}
      {...p}
    />
  ),
  code: ({ node, className, children, ...p }) => {
    const inline = !className;
    return inline ? (
      <code
        style={{
          fontFamily: "var(--font-mono)",
          background: "var(--panel-2)",
          border: "1px solid var(--border-26)",
          borderRadius: 2,
          padding: "0 3px",
          fontSize: "0.92em",
          color: "var(--t-85)",
        }}
        {...p}
      >
        {children}
      </code>
    ) : (
      <code style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--t-85)" }} {...p}>
        {children}
      </code>
    );
  },
  pre: ({ node, ...p }) => (
    <pre
      style={{
        margin: "6px 0",
        padding: "8px 10px",
        background: "var(--panel-2)",
        border: "1px solid var(--border)",
        borderRadius: 2,
        overflowX: "auto",
        lineHeight: 1.45,
      }}
      {...p}
    />
  ),
  blockquote: ({ node, ...p }) => (
    <blockquote
      style={{ margin: "6px 0", paddingLeft: 10, borderLeft: "2px solid var(--border-strong)", color: "var(--t-70)" }}
      {...p}
    />
  ),
  hr: () => <hr style={{ border: "none", borderTop: "1px solid var(--border)", margin: "10px 0" }} />,
  table: ({ node, ...p }) => (
    <div style={{ overflowX: "auto", margin: "6px 0" }}>
      <table
        className="mono"
        style={{ borderCollapse: "collapse", fontSize: 10.5, width: "100%" }}
        {...p}
      />
    </div>
  ),
  th: ({ node, ...p }) => (
    <th
      style={{
        textAlign: "left",
        padding: "3px 6px",
        borderBottom: "1px solid var(--border-strong)",
        color: "var(--t-55)",
        fontWeight: 500,
        whiteSpace: "nowrap",
      }}
      {...p}
    />
  ),
  td: ({ node, ...p }) => (
    <td style={{ padding: "3px 6px", borderBottom: "1px solid var(--border-row)", verticalAlign: "top" }} {...p} />
  ),
};

export const AssistantMarkdown = memo(function AssistantMarkdown({
  children,
  streaming = false,
}: {
  children: string;
  /** True only for the message currently receiving new content - paces its reveal
   * word-by-word instead of rendering instantly (which historical messages still do). */
  streaming?: boolean;
}) {
  const text = useWordReveal(children, streaming);
  return (
    <div
      className="mono"
      style={{ color: "var(--t-85)", fontSize: 11.5, wordBreak: "break-word", overflowWrap: "anywhere" }}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
        {text}
      </ReactMarkdown>
    </div>
  );
});
