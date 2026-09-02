import { useMemo, useState } from "react";
import { useResearchFeed, useFeedFacets } from "@/data/query/use_research_feed";
import { useWatchlist } from "@/data/watchlist";
import { CalendarInput } from "@/components/common/calendar_input";
import { EmptyState, Notice, Popover } from "@/components/common/ui";
import type { FeedContentType, ResearchFeedItem } from "@/domain/models";
import { ChevronRight, ExternalLink } from "lucide-react";

interface Props {
  filter?: string;
  selectedSymbol?: string | null;
  onSelectSymbol?: (symbol: string | null) => void;
}
const DATE_KIND: Record<string, string> = {
  published: "Published",
  ex_date: "Ex-date",
  public_date: "Public date",
  record_date: "Record date",
  disclosure_date: "Disclosed",
  observed: "Observed",
};
function day(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00+07:00` : iso);
  return Number.isFinite(d.getTime())
    ? new Intl.DateTimeFormat("en-CA", {
        timeZone: "Asia/Ho_Chi_Minh",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(d)
    : "";
}
function displayDate(iso?: string | null) {
  const date = day(iso);
  return date
    ? new Intl.DateTimeFormat("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        timeZone: "Asia/Ho_Chi_Minh",
      }).format(new Date(`${date}T00:00:00+07:00`))
    : "—";
}
export function NewsFeed({
  filter = "",
  selectedSymbol = null,
  onSelectSymbol,
}: Props) {
  const [query, setQuery] = useState(filter);
  const [scope, setScope] = useState<"all" | "watchlist" | "selected">("all");
  const [symbols, setSymbols] = useState<string[] | null>(null);
  const [symbolSearch, setSymbolSearch] = useState("");
  const [type, setType] = useState<FeedContentType | "">("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const { items: watched } = useWatchlist();
  const facets = useFeedFacets();
  const invalidDates = !!(from && to && from > to);
  const scopedSymbols = useMemo(() => {
    const base =
      scope === "watchlist"
        ? [
            ...new Set(
              watched.flatMap((i) => [
                i.symbol,
                ...(i.underlyingSymbol ? [i.underlyingSymbol] : []),
              ]),
            ),
          ]
        : scope === "selected"
          ? selectedSymbol
            ? [selectedSymbol]
            : []
          : null;
    return base === null
      ? symbols
      : symbols === null
        ? base
        : base.filter((s) => symbols.includes(s));
  }, [scope, symbols, watched, selectedSymbol]);
  const feed = useResearchFeed({
    symbols: scopedSymbols,
    query,
    contentType: type || undefined,
    dateFrom: from,
    dateTo: to,
    enabled: !invalidDates,
  });
  const clear = () => {
    setQuery("");
    setSymbols(null);
    setType("");
    setFrom("");
    setTo("");
    setScope("all");
  };
  const active = symbols !== null || !!type || !!from || !!to;
  const dateLabel = (item: ResearchFeedItem) =>
    item.date_kind
      ? (DATE_KIND[item.date_kind] ?? "Date")
      : item.content_type === "company_event"
        ? "Event date"
        : "Published";
  return (
    <section aria-label="News feed">
      <div className="section-toolbar">
        <div>
          <h1 className="section-title">News & events</h1>
          <p className="section-subtitle">
            Official disclosures and company events, with source context.
          </p>
        </div>
        <div className="actions">
          <input
            aria-label="Search news"
            placeholder="Search headlines or topics…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <Popover label="News filters" active={active} width={440}>
            {(close) => (
              <>
                <div className="filter-grid">
                  <div>
                    <label className="field">
                      <span>Symbols</span>
                      <input
                        aria-label="Find a news symbol"
                        placeholder="Search symbols…"
                        value={symbolSearch}
                        onChange={(e) => setSymbolSearch(e.target.value)}
                      />
                    </label>
                    <div className="filter-options">
                      <label className="check-row">
                        <input
                          type="checkbox"
                          checked={symbols === null}
                          onChange={() =>
                            setSymbols(symbols === null ? [] : null)
                          }
                        />
                        All symbols
                      </label>
                      {facets.data?.symbols
                        .filter((s) => s.includes(symbolSearch.toUpperCase()))
                        .map((s) => (
                          <label className="check-row" key={s}>
                            <input
                              type="checkbox"
                              checked={symbols?.includes(s) ?? true}
                              onChange={() =>
                                setSymbols((prev) => {
                                  const cur =
                                    prev ?? facets.data?.symbols ?? [];
                                  return cur.includes(s)
                                    ? cur.filter((x) => x !== s)
                                    : [...cur, s];
                                })
                              }
                            />
                            {s}
                          </label>
                        ))}
                      {facets.isLoading && <p>Loading symbols…</p>}
                      {facets.isError && (
                        <button
                          className="btn btn-link"
                          onClick={() => void facets.refetch()}
                        >
                          Retry symbol list
                        </button>
                      )}
                    </div>
                  </div>
                  <label className="field">
                    <span>Content</span>
                    <select
                      aria-label="Content type"
                      value={type}
                      onChange={(e) => setType(e.target.value as typeof type)}
                    >
                      <option value="">Disclosures & events</option>
                      <option value="exchange_disclosure">Disclosures</option>
                      <option value="company_event">Company events</option>
                    </select>
                  </label>
                </div>
                <div className="filter-grid filter-dates">
                  <CalendarInput
                    ariaLabel="Date from"
                    value={from}
                    onChange={setFrom}
                  />
                  <CalendarInput
                    ariaLabel="Date to"
                    value={to}
                    onChange={setTo}
                  />
                </div>
                <p className="section-subtitle">
                  Dates refer to the labelled publication or event date.
                </p>
                {invalidDates && (
                  <p role="alert" className="field-error">
                    Start date must not be after end date.
                  </p>
                )}
                <div className="popover-footer">
                  <button className="btn btn-link" onClick={clear}>
                    Clear filters
                  </button>
                  <button className="btn" onClick={close}>
                    Done
                  </button>
                </div>
              </>
            )}
          </Popover>
        </div>
      </div>
      <div className="section-toolbar">
        <div className="segmented" aria-label="News scope">
          {(
            [
              ["all", "All market"],
              ["watchlist", "Watchlist"],
              ["selected", "Selected instrument"],
            ] as const
          ).map(([key, label]) => (
            <button
              className={`btn ${scope === key ? "is-active" : ""}`}
              key={key}
              disabled={key === "selected" && !selectedSymbol}
              aria-pressed={scope === key}
              onClick={() => setScope(key)}
            >
              {label}
              {key === "selected" && selectedSymbol
                ? ` · ${selectedSymbol}`
                : ""}
            </button>
          ))}
        </div>
        <span className="section-subtitle">
          {feed.items.length} loaded{active ? " · Filters active" : ""}
        </span>
      </div>
      {invalidDates ? (
        <Notice error>Choose a valid date range.</Notice>
      ) : feed.isLoading ? (
        <EmptyState title="Loading news…" />
      ) : feed.isError ? (
        <EmptyState
          title="Could not load the feed"
          action={
            <button className="btn" onClick={feed.refetch}>
              Retry
            </button>
          }
        >
          Your filters have been kept.
        </EmptyState>
      ) : feed.items.length === 0 ? (
        <EmptyState
          title="No matching news or events"
          action={
            <button className="btn" onClick={clear}>
              Clear filters
            </button>
          }
        >
          Try another topic, symbol or date range.
        </EmptyState>
      ) : (
        <div className="table-scroll">
          <table className="data-table news-table">
            <thead>
              <tr>
                <th aria-label="Expand" />
                <th>Date</th>
                <th>Symbol</th>
                <th>Type</th>
                <th>Headline</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {feed.items.map((item) => {
                const expanded = openId === item.id;
                const when = item.display_date ?? item.published_at;
                const upcoming = day(when) > day(new Date().toISOString());
                return (
                  <FeedRows
                    key={item.id}
                    item={item}
                    expanded={expanded}
                    when={when}
                    upcoming={upcoming}
                    dateLabel={dateLabel(item)}
                    toggle={() => setOpenId(expanded ? null : item.id)}
                    onSelectSymbol={onSelectSymbol}
                    onFilterSymbol={() => {
                      setScope("all");
                      setSymbols(item.symbol ? [item.symbol] : null);
                    }}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {feed.hasNextPage && !invalidDates && !feed.isError && (
        <div className="load-more">
          <button
            className="btn"
            onClick={feed.fetchNextPage}
            disabled={feed.isFetchingNextPage}
          >
            {feed.isFetchingNextPage ? "Loading…" : "Load older"}
          </button>
        </div>
      )}
    </section>
  );
}
function FeedRows({
  item,
  expanded,
  when,
  upcoming,
  dateLabel,
  toggle,
  onSelectSymbol,
  onFilterSymbol,
}: {
  item: ResearchFeedItem;
  expanded: boolean;
  when?: string | null;
  upcoming: boolean;
  dateLabel: string;
  toggle: () => void;
  onSelectSymbol?: Props["onSelectSymbol"];
  onFilterSymbol: () => void;
}) {
  return (
    <>
      <tr className={expanded ? "is-selected" : ""} onClick={toggle}>
        <td className="row-control">
          <button
            className="icon-btn"
            aria-label={`${expanded ? "Collapse" : "Expand"} ${item.title_en}`}
            aria-expanded={expanded}
            onClick={(e) => {
              e.stopPropagation();
              toggle();
            }}
          >
            <ChevronRight
              size={14}
              style={{ transform: expanded ? "rotate(90deg)" : undefined }}
            />
          </button>
        </td>
        <td>
          <span>{displayDate(when)}</span>
          <small>
            {dateLabel}
            {upcoming ? " · Upcoming" : ""}
          </small>
        </td>
        <td>
          {item.symbol ? (
            <button
              className="btn btn-link"
              onClick={(e) => {
                e.stopPropagation();
                onSelectSymbol?.(item.symbol);
              }}
            >
              {item.symbol}
            </button>
          ) : (
            "—"
          )}
        </td>
        <td>
          <span className="badge">
            {item.content_type === "company_event" ? "Event" : "Disclosure"}
          </span>
        </td>
        <td className="news-headline">
          {item.title_en}
          {!item.title_en_exact && <small>Classified headline</small>}
        </td>
        <td>
          {item.source}
          {item.source_url && (
            <a
              className="source-link"
              href={item.source_url}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`Official source for ${item.symbol ?? item.title_en}`}
              onClick={(e) => e.stopPropagation()}
            >
              <ExternalLink size={13} />
            </a>
          )}
        </td>
      </tr>
      {expanded && (
        <tr className="news-expanded">
          <td colSpan={6}>
            <article>
              <h2>{item.title_en}</h2>
              <p className="section-subtitle">
                {item.category_en} · {dateLabel}: {displayDate(when)}
              </p>
              {!item.title_en_exact && (
                <p className="section-subtitle">
                  Classified from the source disclosure; this headline is not a
                  verbatim translation.
                </p>
              )}
              <div className="actions">
                {item.source_url && (
                  <a
                    className="btn"
                    href={item.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Official source <ExternalLink size={13} />
                  </a>
                )}
                {item.symbol && (
                  <button className="btn" onClick={onFilterSymbol}>
                    Filter news by {item.symbol}
                  </button>
                )}
                <span className="badge">
                  Original language:{" "}
                  {(item.source_language || "vi").toUpperCase()}
                </span>
              </div>
              <div className="original-source">
                <strong>Original (Vietnamese)</strong>
                <p>{item.title}</p>
                {item.summary && <p>{item.summary}</p>}
              </div>
            </article>
          </td>
        </tr>
      )}
    </>
  );
}
