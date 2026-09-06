import { useEffect, useMemo, useRef, useState } from "react";
import { useResearchFeed } from "@/data/query";
import { DASH } from "@/components/common/grid_table";
import { CalendarInput } from "@/components/common/calendar_input";
import { FilterPopover } from "@/components/common/filter_popover";
import type { FeedContentType, ResearchFeedItem } from "@/domain/models";
import { MarketOverviewStrip } from "@/features/watchlist/market_overview_strip";

interface NewsFeedProps {
  /** Committed header query (`?q=`), searched against symbols and news text in SQL. */
  filter?: string;
  selectedSymbol?: string | null;
  onSelectSymbol?: (symbol: string | null) => void;
}

const VN_TZ = "Asia/Ho_Chi_Minh";

type EventType = "DISCLOSURE" | "EVENT";
const ALL_EVENT_TYPES: EventType[] = ["DISCLOSURE", "EVENT"];

interface NewsFilterState {
  symbols: string[] | null; // null = all
  types: EventType[]; // subset of ALL_EVENT_TYPES
  from: string; // ISO or ""
  to: string;
}
const EMPTY_NEWS_FILTER: NewsFilterState = { symbols: null, types: [...ALL_EVENT_TYPES], from: "", to: "" };

function newsFilterActive(f: NewsFilterState): boolean {
  return f.symbols !== null || f.types.length !== ALL_EVENT_TYPES.length || f.from !== "" || f.to !== "";
}

/** Column header styled to match the Research registry (grid_table HEAD_STYLE). */
const TH: React.CSSProperties = {
  padding: "5px 8px",
  textAlign: "left",
  color: "var(--t-92)",
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

/** Filter layout shared with the registry; dates never change the page width. */
function NewsFilterDropdown({
  symbolOptions,
  value,
  onChange,
}: {
  symbolOptions: string[];
  value: NewsFilterState;
  onChange: (next: NewsFilterState) => void;
}) {
  const [dateReset, setDateReset] = useState(0);
  const toggleSym = (symbol: string) => {
    const current = value.symbols ?? symbolOptions;
    const next = current.includes(symbol) ? current.filter((s) => s !== symbol) : [...current, symbol];
    onChange({ ...value, symbols: next.length === symbolOptions.length ? null : next });
  };
  const toggleType = (type: EventType) => onChange({
    ...value,
    types: value.types.includes(type) ? value.types.filter((t) => t !== type) : [...value.types, type],
  });
  return (
    <FilterPopover active={newsFilterActive(value)} label="News filters">
      <div className="filter-columns">
        <section className="filter-column" aria-label="SYMBOL">
          <div className="filter-label">SYMBOL</div>
          <label className="filter-check filter-all">
            <input type="checkbox" checked={value.symbols === null} aria-label="All symbols"
              onChange={() => onChange({ ...value, symbols: value.symbols === null ? [] : null })} />
            All
          </label>
          <div className="filter-options" aria-label="SYMBOL options" tabIndex={0}>
            {symbolOptions.map((symbol) => (
              <label className="filter-check" key={symbol}>
                <input type="checkbox" checked={value.symbols === null || value.symbols.includes(symbol)} onChange={() => toggleSym(symbol)} />
                <span>{symbol}</span>
              </label>
            ))}
            {!symbolOptions.length && <span className="filter-empty">No symbols</span>}
          </div>
        </section>
        <section className="filter-column" aria-label="EVENT TYPE">
          <div className="filter-label">EVENT TYPE</div>
          <label className="filter-check filter-all">
            <input type="checkbox" checked={value.types.length === ALL_EVENT_TYPES.length} aria-label="All event types"
              onChange={() => onChange({ ...value, types: value.types.length === ALL_EVENT_TYPES.length ? [] : [...ALL_EVENT_TYPES] })} />
            All
          </label>
          <div className="filter-options" aria-label="EVENT TYPE options">
            {ALL_EVENT_TYPES.map((type) => (
              <label className="filter-check" key={type}>
                <input type="checkbox" checked={value.types.includes(type)} onChange={() => toggleType(type)} />
                <span>{type}</span>
              </label>
            ))}
          </div>
        </section>
      </div>
      <div className="filter-date-section">
        <div className="filter-date-heading">
          <span className="filter-label">PUBLISH DATE</span>
          <button type="button" className="filter-clear focus-ring" onClick={() => { setDateReset(n => n + 1); onChange(EMPTY_NEWS_FILTER); }}>CLEAR</button>
        </div>
        <div className="filter-dates">
          <div><div className="filter-date-label">From Date</div><CalendarInput resetKey={dateReset} ariaLabel="Publish date from" value={value.from} onChange={(iso) => onChange({ ...value, from: iso })} /></div>
          <div><div className="filter-date-label">To Date</div><CalendarInput resetKey={dateReset} ariaLabel="Publish date to" value={value.to} onChange={(iso) => onChange({ ...value, to: iso })} /></div>
        </div>
      </div>
    </FilterPopover>
  );
}

function FeedRow({
  item,
  onSelectSymbol,
  highlighted,
  isNew = false,
}: {
  item: ResearchFeedItem;
  onSelectSymbol?: (s: string) => void;
  highlighted: boolean;
  isNew?: boolean;
}) {
  const isEvent = item.content_type === "company_event";
  const hasOriginal = item.title && item.title !== item.title_en;
  const category = item.category_en && (item.category_en !== item.category || item.source_language !== "vi") ? item.category_en : null;
  return (
      <tr
        className={`news-row${highlighted ? " is-search-match" : ""}${isNew ? " is-new" : ""}`}
        data-symbol={item.symbol ?? undefined}
        style={{
          background: highlighted ? "var(--panel-3)" : "transparent",
          borderBottom: "1px solid var(--border-row)",
          verticalAlign: "top",
        }}
      >
        <td style={{ ...TD, paddingTop: 8, color: "var(--t-92)", whiteSpace: "nowrap" }}>{fmtTime(item.published_at)}</td>
        <td style={{ ...TD, paddingTop: 8, whiteSpace: "nowrap" }}>
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
        <td style={{ ...TD, paddingTop: 8, whiteSpace: "nowrap", color: isEvent ? "var(--accent-violet)" : "var(--t-55)" }}>
          {isEvent ? "EVENT" : "DISCLOSURE"}
        </td>
        <td style={{ ...TD, paddingTop: 7, paddingBottom: 8, color: "var(--t-85)", whiteSpace: "normal", lineHeight: 1.45 }}>
          <div style={{ fontWeight: 500 }}>{item.title_en}</div>
          {!item.title_en_exact && (
            <span
              title="Classified from the disclosure category — see the original Vietnamese title below"
              style={{ marginLeft: 6, color: "var(--t-42)", fontSize: 10 }}
            >
              Classified headline
            </span>
          )}
          {category && <div style={{ marginTop: 2, color: "var(--t-50)", fontSize: 10 }}>{category}</div>}
          {item.summary && <div style={{ marginTop: 4, color: "var(--t-70)" }}>{item.summary}</div>}
          {hasOriginal && <div style={{ marginTop: 4, color: "var(--t-55)", fontSize: 10.5 }}><span style={{ color: "var(--t-42)" }}>Original (Vietnamese): </span>{item.title}</div>}
        </td>
        <td style={{ ...TD, paddingTop: 8, whiteSpace: "nowrap", color: "var(--t-92)" }}>{item.source}</td>
        <td style={{ ...TD, paddingTop: 8, textAlign: "center" }}>
          {item.source_url ? (
            <a
              href={item.source_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              title="Open official source"
              style={{ color: "var(--accent)", textDecoration: "none" }}
            >
              ↗
            </a>
          ) : (
            <span style={{ color: "var(--t-42)" }}>{DASH}</span>
          )}
        </td>
      </tr>
  );
}

export function NewsFeed({ filter = "", selectedSymbol = null, onSelectSymbol }: NewsFeedProps) {
  const term = filter.trim().replace(/^\//, "").trim();
  const query = term || undefined;

  const [nf, setNf] = useState<NewsFilterState>(EMPTY_NEWS_FILTER);

  // A global text search spans the feed even when an instrument panel is open.
  const symbol = query ? undefined : selectedSymbol ?? undefined;

  // EVENT TYPE maps to the server content_type only when exactly one is selected —
  // keeps the cursor pagination working; SYMBOL + date are filtered client-side.
  const contentType: FeedContentType | undefined =
    nf.types.length === 1
      ? nf.types[0] === "DISCLOSURE"
        ? "exchange_disclosure"
        : "company_event"
      : undefined;

  const { items: rawItems, isLoading, isError, isEmpty, hasNextPage, fetchNextPage, isFetchingNextPage, refetch } =
    useResearchFeed({ symbol, contentType, query });

  const symbolOptions = useMemo(
    () => [...new Set(rawItems.map((i) => i.symbol).filter((s): s is string => !!s))].sort(),
    [rawItems],
  );

  const items = useMemo(
    () =>
      rawItems.filter((it) => {
        if (nf.symbols !== null && (!it.symbol || !nf.symbols.includes(it.symbol))) return false;
        if (nf.types.length === 0) return false;
        if (nf.types.length === 1) {
          const isEvent = it.content_type === "company_event";
          if (nf.types[0] === "EVENT" ? !isEvent : isEvent) return false;
        }
        const d = (it.published_at ?? "").slice(0, 10);
        if (nf.from && (!d || d < nf.from)) return false;
        if (nf.to && (!d || d > nf.to)) return false;
        return true;
      }),
    [rawItems, nf],
  );

  const subtitle = useMemo(() => {
    if (symbol) return `feed for ${symbol}`;
    if (query) return `search · “${query}”`;
    return "HOSE disclosures & company events";
  }, [symbol, query]);

  // Rows that weren't on screen last render wipe in (a fresh page / filter change
  // doesn't cascade the whole list — only the first paint is skipped entirely).
  const seenIds = useRef<Set<string>>(new Set());
  const settled = useRef(false);
  const isNewRow = (id: string) => settled.current && !seenIds.current.has(id);
  useEffect(() => {
    seenIds.current = new Set(items.map((it) => it.id));
    settled.current = true;
  }, [items]);

  return (
    <div className="page-shell">
      <MarketOverviewStrip />
      <div className="page-title-row" style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
        <span className="heading" style={{ fontSize: 14, fontWeight: 700, letterSpacing: "0.02em" }}>
          News
        </span>
        <span style={{ fontSize: 10.5, color: "var(--t-42)", fontStyle: "italic" }}>“{subtitle}”</span>
        <span style={{ marginLeft: "auto" }}>
          <NewsFilterDropdown symbolOptions={symbolOptions} value={nf} onChange={setNf} />
        </span>
      </div>
      <div className="news-table-scroll">
      <table className="mono grid-lined news-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
        <colgroup><col style={{ width: 96 }} /><col style={{ width: 72 }} /><col style={{ width: 96 }} /><col /><col style={{ width: 90 }} /><col style={{ width: 40 }} /></colgroup>
        <thead>
          <tr style={{ borderBottom: "1px solid var(--border-strong)" }}>
            <th style={TH}>PUBLISH DATE</th>
            <th style={TH}>SYMBOL</th>
            <th style={TH}>EVENT TYPE</th>
            <th style={TH}>HEADLINE</th>
            <th style={TH}>SOURCE</th>
            <th style={{ ...TH, textAlign: "center", width: 40 }}>LINK</th>
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            <tr>
              <td colSpan={6} style={{ padding: "56px 0", textAlign: "center", fontSize: 12, color: "var(--t-46)" }}>
                Loading…
              </td>
            </tr>
          ) : isError ? (
            <tr>
              <td colSpan={6} style={{ padding: "56px 0", textAlign: "center", fontSize: 12, color: "var(--down)" }}>
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
              <td colSpan={6} style={{ padding: "56px 0", textAlign: "center", fontSize: 12, color: "var(--t-46)" }}>
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
                isNew={isNewRow(item.id)}
                onSelectSymbol={(s) => onSelectSymbol?.(s)}
                highlighted={!!item.symbol && (item.symbol === selectedSymbol || item.symbol.toUpperCase() === term.toUpperCase())}
              />
            ))
          )}
        </tbody>
      </table>

      {hasNextPage && !isLoading && !isError && (
        <div style={{ textAlign: "center", padding: "16px 0 12px" }}>
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
    </div>
  );
}
