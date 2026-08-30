import { useMemo, useState } from "react";
import { useResearchNews } from "@/data/query";
import { DASH } from "@/components/common/grid_table";
import type { ResearchNewsItem } from "@/domain/models";

interface NewsFeedProps {
  /** Shared header filter (`?q=`). A bare token that looks like a ticker filters by
   *  symbol; anything else is a free-text headline search. */
  filter?: string;
  selectedSymbol?: string | null;
  onSelectSymbol?: (symbol: string | null) => void;
}

const TICKER_RE = /^[A-Z][A-Z0-9]{1,11}$/;
const VN_TZ = "Asia/Ho_Chi_Minh";

function fmtTime(iso: string | null): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return DASH;
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: VN_TZ,
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

function NewsRow({
  item,
  expanded,
  onToggle,
  onSelectSymbol,
}: {
  item: ResearchNewsItem;
  expanded: boolean;
  onToggle: () => void;
  onSelectSymbol?: (s: string) => void;
}) {
  return (
    <>
      <tr
        tabIndex={0}
        onClick={onToggle}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onToggle())}
        style={{
          cursor: "pointer",
          height: 26,
          background: expanded ? "var(--panel-3)" : "transparent",
          borderBottom: "1px solid var(--border-row)",
        }}
      >
        <td style={{ padding: "0 10px", color: "var(--t-50)", whiteSpace: "nowrap" }}>
          {fmtTime(item.published_at)}
        </td>
        <td style={{ padding: "0 10px", whiteSpace: "nowrap" }}>
          {item.symbols.length === 0 ? (
            <span style={{ color: "var(--t-42)" }}>{DASH}</span>
          ) : (
            item.symbols.slice(0, 3).map((s, i) => (
              <span key={s}>
                {i > 0 && <span style={{ color: "var(--t-40)" }}>, </span>}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelectSymbol?.(s);
                  }}
                  style={{
                    background: "none",
                    border: "none",
                    padding: 0,
                    font: "inherit",
                    cursor: "pointer",
                    color: "var(--accent)",
                  }}
                >
                  {s}
                </button>
              </span>
            ))
          )}
        </td>
        <td style={{ padding: "0 10px", color: "var(--t-55)", whiteSpace: "nowrap", maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis" }}>
          {item.category ?? DASH}
        </td>
        <td style={{ padding: "0 10px", color: "var(--t-85)" }}>{item.title}</td>
      </tr>
      {expanded && (
        <tr style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--border-row)" }}>
          <td colSpan={4} style={{ padding: "10px 14px 12px" }}>
            <div style={{ fontSize: 11, color: "var(--t-70)", lineHeight: 1.55, maxWidth: 760 }}>
              {item.summary ?? "No summary text was published with this disclosure."}
            </div>
            <div style={{ marginTop: 8, display: "flex", gap: 14, fontSize: 10, color: "var(--t-46)" }}>
              <span>SOURCE {item.source}</span>
              {item.url && (
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  style={{ color: "var(--accent)" }}
                >
                  OPEN DISCLOSURE ↗
                </a>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export function NewsFeed({ filter = "", selectedSymbol = null, onSelectSymbol }: NewsFeedProps) {
  const term = filter.trim().replace(/^\//, "").trim();
  const looksLikeTicker = TICKER_RE.test(term.toUpperCase());
  const symbol = looksLikeTicker ? term.toUpperCase() : selectedSymbol ?? undefined;
  const query = looksLikeTicker ? undefined : term || undefined;

  const { items, isLoading, isError, isEmpty, refetch } = useResearchNews({ symbol, query });
  const [openId, setOpenId] = useState<number | null>(null);

  const subtitle = useMemo(() => {
    if (symbol) return `disclosures linked to ${symbol}`;
    if (query) return `headline search · “${query}”`;
    return "HOSE issuer & exchange disclosures";
  }, [symbol, query]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 3 }}>
        <span className="heading" style={{ fontSize: 14, fontWeight: 700, letterSpacing: "0.02em" }}>
          News
        </span>
        <span style={{ fontSize: 10.5, color: "var(--t-42)", fontStyle: "italic" }}>“{subtitle}”</span>
      </div>
      <p style={{ fontSize: 11, color: "var(--t-46)", marginBottom: 14 }}>
        {isLoading
          ? "Loading disclosures…"
          : isError
          ? "feed unavailable"
          : `${items.length} item${items.length === 1 ? "" : "s"} · disclosed near the stated time — timing only, not causation`}
      </p>

      <table className="mono" style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
        <thead>
          <tr style={{ borderBottom: "1px solid var(--border-strong)" }}>
            <th style={{ padding: "0 10px 6px", textAlign: "left", fontSize: 9.5, letterSpacing: "0.06em", color: "var(--t-46)", fontWeight: 400 }}>TIME</th>
            <th style={{ padding: "0 10px 6px", textAlign: "left", fontSize: 9.5, letterSpacing: "0.06em", color: "var(--t-46)", fontWeight: 400 }}>SYMBOL</th>
            <th style={{ padding: "0 10px 6px", textAlign: "left", fontSize: 9.5, letterSpacing: "0.06em", color: "var(--t-46)", fontWeight: 400 }}>CATEGORY</th>
            <th style={{ padding: "0 10px 6px", textAlign: "left", fontSize: 9.5, letterSpacing: "0.06em", color: "var(--t-46)", fontWeight: 400 }}>HEADLINE</th>
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            <tr>
              <td colSpan={4} style={{ padding: "56px 0", textAlign: "center", fontSize: 12, color: "var(--t-46)" }}>
                Loading disclosures…
              </td>
            </tr>
          ) : isError ? (
            <tr>
              <td colSpan={4} style={{ padding: "56px 0", textAlign: "center", fontSize: 12, color: "var(--down)" }}>
                Could not load the news feed.{" "}
                <button
                  type="button"
                  onClick={() => refetch()}
                  style={{ background: "none", border: "none", color: "var(--accent)", cursor: "pointer", font: "inherit" }}
                >
                  Retry
                </button>
              </td>
            </tr>
          ) : isEmpty ? (
            <tr>
              <td colSpan={4} style={{ padding: "56px 0", textAlign: "center", fontSize: 12, color: "var(--t-46)" }}>
                {symbol || query
                  ? "No disclosures match this filter yet."
                  : "No disclosures ingested yet — pending the next ingestion run."}
              </td>
            </tr>
          ) : (
            items.map((item) => (
              <NewsRow
                key={item.id}
                item={item}
                expanded={openId === item.id}
                onToggle={() => setOpenId((cur) => (cur === item.id ? null : item.id))}
                onSelectSymbol={(s) => onSelectSymbol?.(s)}
              />
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
