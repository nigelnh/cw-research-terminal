import { useEffect, useId, useRef, useState } from "react";

export interface WatchlistSearchOption {
  symbol: string;
  kind: "stock" | "cw";
  name: string;
  exchange: string | null;
  underlying: string | null;
}

export const normalizeSearch = (text: string) => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/gi, "d").trim().toUpperCase();

export function searchSuggestions(options: WatchlistSearchOption[], query: string): WatchlistSearchOption[] {
  const term = normalizeSearch(query);
  if (!term) return [];
  return options.filter(option => normalizeSearch(option.symbol).startsWith(term) || normalizeSearch(option.name).startsWith(term))
    .sort((a, b) => Number(a.kind === "cw") - Number(b.kind === "cw") || a.symbol.localeCompare(b.symbol, "en"));
}

export function matchingSymbols(options: WatchlistSearchOption[], query: string): Set<string> {
  const term = normalizeSearch(query);
  if (!term) return new Set();
  // An exact ticker chooses that instrument, even if its name occurs in CW descriptions.
  const exact = options.find(option => option.symbol === term);
  return new Set((exact ? [exact] : searchSuggestions(options, term)).map(option => option.symbol));
}

/** Preserve hierarchy and existing sort/pin order while lifting search matches. */
export function prioritizeWatchlist<T extends { symbol: string; kind: "stock" | "cw"; underlying: string | null }>(rows: T[], matches: Set<string>) {
  const stocks = new Set(rows.filter(row => row.kind === "stock").map(row => row.symbol));
  const groups = rows.filter(row => row.kind === "stock").map(parent => ({
    parent,
    children: rows.filter(row => row.kind === "cw" && row.underlying === parent.symbol),
  }));
  const matchedGroups = new Set(rows.filter(row => matches.has(row.symbol)).map(row => row.kind === "stock" ? row.symbol : row.underlying));
  groups.sort((a, b) => Number(matchedGroups.has(b.parent.symbol)) - Number(matchedGroups.has(a.parent.symbol)));
  const priority = (a: T, b: T) => Number(matches.has(b.symbol)) - Number(matches.has(a.symbol));
  const orphans = rows.filter(row => row.kind === "cw" && !stocks.has(row.underlying ?? "")).sort(priority);
  const grouped = groups.flatMap(({ parent, children }) => [parent, ...children.sort(priority)]);
  const highlighted = new Set(rows.filter(row => matches.has(row.symbol) || (row.kind === "cw" && matches.has(row.underlying ?? ""))).map(row => row.symbol));
  return { rows: [...orphans.filter(row => matches.has(row.symbol)), ...grouped, ...orphans.filter(row => !matches.has(row.symbol))], highlighted };
}

export function WatchlistSymbolSearch({ options, value, onSubmit, scope = "watchlist" }: {
  options: WatchlistSearchOption[];
  value: string;
  onSubmit: (value: string) => void;
  scope?: "watchlist" | "research";
}) {
  const [draft, setDraft] = useState(value);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const anchor = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  const suggestions = searchSuggestions(options, draft);
  const activeIndex = Math.min(active, suggestions.length - 1);
  const shown = open && draft.trim().length > 0;
  useEffect(() => setDraft(value), [value]);
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => { if (!anchor.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);
  useEffect(() => {
    if (shown && activeIndex >= 0) anchor.current?.querySelector(`[data-option-index="${activeIndex}"]`)?.scrollIntoView?.({ block: "nearest" });
  }, [activeIndex, shown]);
  const choose = (symbol: string) => { setDraft(symbol); setActive(-1); setOpen(false); input.current?.focus(); };
  return <div className="watchlist-search" ref={anchor} onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget as Node)) setOpen(false);
  }}>
    <div className="watchlist-search-control">
      <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="8.5" cy="8.5" r="5.5" /><path d="m13 13 4 4" /></svg>
      <input ref={input} role="combobox" aria-label={`Search ${scope} symbols`} placeholder="Search symbol" title="Press Enter to search"
        value={draft} aria-autocomplete="list" aria-expanded={shown} aria-controls={shown ? id : undefined}
        aria-activedescendant={shown && activeIndex >= 0 ? `${id}-${activeIndex}` : undefined}
        onChange={event => { setDraft(event.target.value); setActive(-1); setOpen(Boolean(event.target.value.trim())); }}
        onKeyDown={event => {
          if (event.nativeEvent.isComposing) return;
          if (event.key === "Escape") { event.preventDefault(); setOpen(false); }
          if (draft.trim() && suggestions.length > 0 && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
            event.preventDefault(); setOpen(true);
            setActive(current => !shown || current < 0 ? (event.key === "ArrowDown" ? 0 : suggestions.length - 1) : Math.max(0, Math.min(suggestions.length - 1, current + (event.key === "ArrowDown" ? 1 : -1))));
          }
          if (event.key === "Enter") {
            event.preventDefault();
            const query = shown && activeIndex >= 0 ? suggestions[activeIndex].symbol : event.currentTarget.value.trim();
            choose(query);
            onSubmit(query);
          }
        }} />
      {(draft || value) && <button type="button" aria-label={`Clear ${scope} search`} className="focus-ring" onClick={() => { choose(""); onSubmit(""); }}>
        <svg aria-hidden="true" viewBox="0 0 20 20" stroke="currentColor" strokeWidth="1.5"><path d="m5 5 10 10M15 5 5 15" /></svg>
      </button>}
    </div>
    {shown && <div className="watchlist-search-results" role="listbox" id={id} aria-label={`${scope === "research" ? "Research" : "Watchlist"} matches`}>
      {suggestions.map((option, index) => <div key={option.symbol} id={`${id}-${index}`} role="option" aria-selected={index === activeIndex}
        data-option-index={index} className="watchlist-search-option" onMouseDown={event => event.preventDefault()} onClick={() => choose(option.symbol)}>
        <span className="mono" style={{ color: option.kind === "stock" ? "var(--accent)" : "var(--t-92)" }}>{option.symbol}</span>
        <span className="watchlist-search-name" title={option.name || option.underlying || undefined}>{option.name || option.underlying || ""}</span>
        <span className="watchlist-search-kind">{option.kind === "stock" ? "Stock" : "CW"}{option.exchange ? ` · ${option.exchange}` : ""}</span>
      </div>)}
      {!suggestions.length && <div className="watchlist-search-empty">No matching symbols in this {scope === "research" ? "registry" : "watchlist"}.</div>}
    </div>}
  </div>;
}
