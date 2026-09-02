import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

/**
 * Grid Terminal-styled Markdown for assistant messages. Compact, restrained spacing,
 * IBM Plex Mono, headings distinguishable but small, tables scroll inside the ~360px
 * panel. Renders partial Markdown cleanly while a response streams.
 */

const H_BASE: React.CSSProperties = {
  fontFamily: "var(--font-sans)",
  fontWeight: 700,
  letterSpacing: "0.02em",
  color: "var(--t-92)",
  margin: "12px 0 4px",
  lineHeight: 1.3,
};

const COMPONENTS: Components = {
  h1: ({ node, ...p }) => <div style={{ ...H_BASE, fontSize: 17 }} {...p} />,
  h2: ({ node, ...p }) => <div style={{ ...H_BASE, fontSize: 16 }} {...p} />,
  h3: ({ node, ...p }) => <div style={{ ...H_BASE, fontSize: 14 }} {...p} />,
  h4: ({ node, ...p }) => <div style={{ ...H_BASE, fontSize: 14 }} {...p} />,
  h5: ({ node, ...p }) => <div style={{ ...H_BASE, fontSize: 14 }} {...p} />,
  h6: ({ node, ...p }) => <div style={{ ...H_BASE, fontSize: 14 }} {...p} />,
  p: ({ node, ...p }) => (
    <p style={{ margin: "4px 0", lineHeight: 1.55 }} {...p} />
  ),
  ul: ({ node, ...p }) => (
    <ul
      style={{
        margin: "4px 0",
        paddingLeft: 16,
        display: "flex",
        flexDirection: "column",
        gap: 2,
      }}
      {...p}
    />
  ),
  ol: ({ node, ...p }) => (
    <ol
      style={{
        margin: "4px 0",
        paddingLeft: 18,
        display: "flex",
        flexDirection: "column",
        gap: 2,
      }}
      {...p}
    />
  ),
  li: ({ node, ...p }) => <li style={{ lineHeight: 1.5 }} {...p} />,
  strong: ({ node, ...p }) => (
    <strong style={{ color: "var(--t-92)", fontWeight: 700 }} {...p} />
  ),
  em: ({ node, ...p }) => <em style={{ color: "var(--t-70)" }} {...p} />,
  a: ({ node, ...p }) => (
    <a
      target="_blank"
      rel="noopener noreferrer"
      style={{
        color: "var(--accent)",
        textDecoration: "underline",
        textUnderlineOffset: 2,
      }}
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
      <code
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 13,
          color: "var(--t-85)",
        }}
        {...p}
      >
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
      style={{
        margin: "6px 0",
        paddingLeft: 10,
        borderLeft: "2px solid var(--border-strong)",
        color: "var(--t-70)",
      }}
      {...p}
    />
  ),
  hr: () => (
    <hr
      style={{
        border: "none",
        borderTop: "1px solid var(--border)",
        margin: "10px 0",
      }}
    />
  ),
  table: ({ node, ...p }) => (
    <div style={{ overflowX: "auto", margin: "6px 0" }}>
      <table
        className="mono"
        style={{ borderCollapse: "collapse", fontSize: 13, width: "100%" }}
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
    <td
      style={{
        padding: "3px 6px",
        borderBottom: "1px solid var(--border-row)",
        verticalAlign: "top",
      }}
      {...p}
    />
  ),
};

export const AssistantMarkdown = memo(function AssistantMarkdown({
  children,
}: {
  children: string;
}) {
  return (
    <div
      style={{
        color: "var(--t-85)",
        fontSize: 14,
        wordBreak: "break-word",
        overflowWrap: "anywhere",
      }}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
        {children}
      </ReactMarkdown>
    </div>
  );
});
