import { useMemo, useState } from "react";
import { useResearchFeed } from "@/data/query";
import { DASH } from "@/components/common/grid_table";
import type { FeedContentType, ResearchFeedItem } from "@/domain/models";

interface NewsFeedProps {
  /** Shared header filter (`?q=`). A bare token that looks like a ticker filters by
   *  symbol; anything else is a free-text search. */
  filter?: string;
  selectedSymbol?: string | null;
  onSelectSymbol?: (symbol: string | null) => void;
}

const TICKER_RE = /^[A-Z][A-Z0-9]{1,11}$/;
const VN_TZ = "Asia/Ho_Chi_Minh";

type SourceFilter = "ALL" | "HOSE" | "SSI" | "VNDIRECT";
type KindFilter = "ALL" | FeedContentType;

/** Column header styled to match the Research registry (grid_table HEAD_STYLE). */
const TH: React.CSSProperties = {
  padding: "5px 8px",
  textAlign: "left",
  color: "var(--t-50)",
  fontWeight: 500,
  whiteSpace: "nowrap",
  userSelect: "none",
};
const TD: React.CSSProperties = { padding: "0 8px" };

function fmtTime(iso: string | null): string {
  if (!iso) return DASH;
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00+07:00` : iso);
  if (Number.isNaN(d.getTime())) return DASH;
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: VN_TZ,
    year: "2-digit",
    month: "short",
    day: "2-digit",
  }).format(d);
}

function FilterChips<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { id: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 2, background: "var(--panel-2)", padding: 2, borderRadius: 3 }}>
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          onClick={() => onChange(o.id)}
          aria-pressed={value === o.id}
          className="focus-ring"
          style={{
            border: "none",
            cursor: "pointer",
            fontFamily: "var(--font-display)",
            fontSize: 10.5,
            letterSpacing: "0.02em",
            padding: "3px 9px",
            borderRadius: 2,
            background: value === o.id ? "var(--panel-active)" : "transparent",
            color: value === o.id ? "var(--t-92)" : "var(--t-55)",
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function FeedRow({
  item,
  expanded,
  onToggle,
  onSelectSymbol,
}: {
  item: ResearchFeedItem;
  expanded: boolean;
  onToggle: () => void;
  onSelectSymbol?: (s: string) => void;
}) {
  const isEvent = item.content_type === "company_event";
  const hasOriginal = item.title && item.title !== item.title_en;
  return (
    <>
      <tr
        tabIndex={0}
        onClick={onToggle}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onToggle())}
        style={{
          cursor: "pointer",
          height: 27,
          background: expanded ? "var(--panel-3)" : "transparent",
          borderBottom: "1px solid var(--border-row)",
        }}
      >
        <td style={{ ...TD, color: "var(--t-50)", whiteSpace: "nowrap" }}>{fmtTime(item.published_at)}</td>
        <td style={{ ...TD, whiteSpace: "nowrap" }}>
          {item.symbol ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onSelectSymbol?.(item.symbol as string);
              }}
              style={{ background: "none", border: "none", padding: 0, font: "inherit", cursor: "pointer", color: "var(--accent)" }}
            >
              {item.symbol}
            </button>
          ) : (
            <span style={{ color: "var(--t-42)" }}>{DASH}</span>
          )}
        </td>
        <td style={{ ...TD, whiteSpace: "nowrap", color: isEvent ? "var(--accent-violet)" : "var(--t-55)" }}>
          {isEvent ? "EVENT" : "DISCLOSURE"}
        </td>
        <td style={{ ...TD, color: "var(--t-85)" }}>
          {item.title_en}
          {!item.title_en_exact && (
            <span
              title="Classified from the disclosure category — see the original Vietnamese title below"
              style={{ marginLeft: 6, color: "var(--t-42)", fontSize: 10 }}
            >
              ~
            </span>
          )}
        </td>
        <td style={{ ...TD, whiteSpace: "nowrap", color: "var(--t-50)" }}>{item.source}</td>
      </tr>
      {expanded && (
        <tr style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--border-row)" }}>
          <td colSpan={5} style={{ padding: "10px 14px 12px" }}>
            <div style={{ fontSize: 12, color: "var(--t-85)", lineHeight: 1.5, maxWidth: 820, fontWeight: 500 }}>
              {item.title_en}
            </div>
            <div style={{ marginTop: 3, fontSize: 10.5, color: "var(--t-50)" }}>
              {item.category_en}
              {!item.title_en_exact && " · headline classified from category, not a translation"}
            </div>
            {item.summary && (
              <div style={{ marginTop: 8, fontSize: 11.5, color: "var(--t-70)", lineHeight: 1.55, maxWidth: 820 }}>
                {item.summary}
                <span style={{ marginLeft: 6, color: "var(--t-42)", fontSize: 10 }}>(original Vietnamese)</span>
              </div>
            )}
            <div style={{ marginTop: 10, display: "flex", gap: 14, fontSize: 10, color: "var(--t-46)", flexWrap: "wrap" }}>
              <span>SOURCE {item.source}</span>
              <span>ORIGINAL LANGUAGE {(item.source_language || "vi").toUpperCase()}</span>
              {item.source_url && (
                <a
                  href={item.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  style={{ color: "var(--accent)" }}
                >
                  OFFICIAL SOURCE ↗
                </a>
              )}
            </div>
            {hasOriginal && (
              <div style={{ marginTop: 8, fontSize: 11, color: "var(--t-55)", lineHeight: 1.5, maxWidth: 820 }}>
                <span style={{ color: "var(--t-42)", fontSize: 10 }}>Original (Vietnamese): </span>
                {item.title}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

export function NewsFeed({ filter = "", selectedSymbol = null, onSelectSymbol }: NewsFeedProps) {
  const term = filter.trim().replace(/^\//, "").trim();
  const looksLikeTicker = TICKER_RE.test(term.toUpperCase());
  const headerSymbol = looksLikeTicker ? term.toUpperCase() : undefined;
  const query = looksLikeTicker ? undefined : term || undefined;

  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("ALL");
  const [kindFilter, setKindFilter] = useState<KindFilter>("ALL");
  const [openId, setOpenId] = useState<string | null>(null);

  const symbol = headerSymbol ?? selectedSymbol ?? undefined;

  const { items, isLoading, isError, isEmpty, hasNextPage, fetchNextPage, isFetchingNextPage, refetch } =
    useResearchFeed({
      symbol,
      source: sourceFilter === "ALL" ? undefined : sourceFilter,
      contentType: kindFilter === "ALL" ? undefined : kindFilter,
      query,
    });

  const subtitle = useMemo(() => {
    if (symbol) return `feed for ${symbol}`;
    if (query) return `search · “${query}”`;
    return "HOSE disclosures & structured company events";
  }, [symbol, query]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 3, flexWrap: "wrap" }}>
        <span className="heading" style={{ fontSize: 14, fontWeight: 700, letterSpacing: "0.02em" }}>
          News
        </span>
        <span style={{ fontSize: 10.5, color: "var(--t-42)", fontStyle: "italic" }}>“{subtitle}”</span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <FilterChips
            value={kindFilter}
            onChange={setKindFilter}
            options={[
              { id: "ALL", label: "ALL" },
              { id: "exchange_disclosure", label: "DISCLOSURES" },
              { id: "company_event", label: "EVENTS" },
            ]}
          />
          <FilterChips
            value={sourceFilter}
            onChange={setSourceFilter}
            options={[
              { id: "ALL", label: "ALL SRC" },
              { id: "HOSE", label: "HOSE" },
              { id: "SSI", label: "SSI" },
              { id: "VNDIRECT", label: "VND" },
            ]}
          />
        </span>
      </div>
      <p style={{ fontSize: 11, color: "var(--t-46)", marginBottom: 14 }}>
        {isLoading
          ? "Loading…"
          : isError
          ? "feed unavailable"
          : `${items.length}${hasNextPage ? "+" : ""} item${items.length === 1 ? "" : "s"} · shown near the stated date — timing only, not causation`}
      </p>

      <table className="mono" style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
        <thead>
          <tr style={{ borderBottom: "1px solid var(--border-strong)" }}>
            <th style={TH}>DATE</th>
            <th style={TH}>SYMBOL</th>
            <th style={TH}>TYPE</th>
            <th style={TH}>HEADLINE</th>
            <th style={TH}>SOURCE</th>
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            <tr>
              <td colSpan={5} style={{ padding: "56px 0", textAlign: "center", fontSize: 12, color: "var(--t-46)" }}>
                Loading…
              </td>
            </tr>
          ) : isError ? (
            <tr>
              <td colSpan={5} style={{ padding: "56px 0", textAlign: "center", fontSize: 12, color: "var(--down)" }}>
                Could not load the feed.{" "}
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
              <td colSpan={5} style={{ padding: "56px 0", textAlign: "center", fontSize: 12, color: "var(--t-46)" }}>
                {symbol || query
                  ? "Nothing matches this filter yet."
                  : "No items ingested yet — pending the next ingestion run."}
              </td>
            </tr>
          ) : (
            items.map((item) => (
              <FeedRow
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

      {hasNextPage && !isLoading && !isError && (
        <div style={{ textAlign: "center", padding: "16px 0 4px" }}>
          <button
            type="button"
            onClick={fetchNextPage}
            disabled={isFetchingNextPage}
            className="focus-ring"
            style={{
              fontFamily: "var(--font-display)",
              fontSize: 11,
              letterSpacing: "0.04em",
              padding: "6px 18px",
              border: "1px solid var(--border-strong)",
              background: "var(--panel-2)",
              color: "var(--t-80)",
              cursor: isFetchingNextPage ? "default" : "pointer",
            }}
          >
            {isFetchingNextPage ? "LOADING…" : "LOAD OLDER"}
          </button>
        </div>
      )}
    </div>
  );
}
