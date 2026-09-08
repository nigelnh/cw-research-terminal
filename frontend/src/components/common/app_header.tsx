import { useMarketContext, marketNow } from "@/data/market_session_store";
import { useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/data/auth";
import { SignInDialog } from "@/features/auth/sign_in_dialog";
import type { GatewayConnectionState, UpstreamFeedState } from "@/data/providers";

export type Tab = "dashboard" | "research" | "news";
export interface GlobalSearchOption {
  symbol: string;
  destination: Tab;
  kind: "stock" | "cw" | "news";
}

const TABS: { id: Tab; label: string }[] = [
  { id: "dashboard", label: "DASHBOARD" },
  { id: "research", label: "RESEARCH" },
  { id: "news", label: "NEWS" },
];

interface AppHeaderProps {
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
  filter: string;
  onFilterChange: (value: string) => void;
  marketSessionActive: boolean;
  marketPhase?: string;
  gatewayState?: GatewayConnectionState;
  upstreamFeedState?: UpstreamFeedState;
  searchOptions?: GlobalSearchOption[];
  onJump?: (option: GlobalSearchOption) => void;
}

function FeedNotice() {
  const { feedStatus } = useMarketContext();
  if (!feedStatus || ["AVAILABLE", "SESSION_PAUSED"].includes(feedStatus.code)) return null;
  // Truncates rather than pushing the group wider. The end column is a 1fr track with
  // nowrap, so an unshrinkable child overflows LEFTWARDS and slides under the centred
  // search box - which paints on top of it, hiding the clock entirely.
  const detail = feedStatus.lastDataAt
    ? `${feedStatus.message} Last data: ${feedStatus.lastDataAt}`
    : feedStatus.message;
  return <div role="status" title={detail}
    style={{ color: "var(--flat)", fontSize: 11, minWidth: 0, flex: "0 1 auto",
             overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
    {feedStatus.message}
  </div>;
}

const VN_TZ = "Asia/Ho_Chi_Minh";

/**
 * "Aug 29, 2026 · 21:43:07 ICT" in Vietnam local time. Its own component + interval so
 * the once-per-second tick re-renders only this span, not the whole header.
 */
function HeaderClock() {
  const [now, setNow] = useState(() => marketNow());
  useEffect(() => {
    const id = window.setInterval(() => setNow(marketNow()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const d = new Date(now);
  const date = new Intl.DateTimeFormat("en-US", {
    timeZone: VN_TZ,
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(d);
  const time = new Intl.DateTimeFormat("en-GB", {
    timeZone: VN_TZ,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(d);
  return <span className="mono">{`${date} · ${time} ICT`}</span>;
}

const TAB_BASE: React.CSSProperties = {
  padding: "4px 12px",
  borderRadius: 2,
  border: "none",
  cursor: "pointer",
  fontFamily: "inherit",
  fontSize: 11,
  letterSpacing: "0.02em",
};

function SignInControl() {
  const { user, status, isConfigured, signOut } = useAuth();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [menuOpen]);

  if (!isConfigured) return null;
  if (status === "loading") {
    return <span style={{ fontSize: 11, color: "var(--t-50)" }} aria-hidden>·</span>;
  }

  if (status === "anonymous") {
    return (
      <>
        <button
          type="button"
          onClick={() => setDialogOpen(true)}
          className="focus-ring"
          style={{
            padding: "4px 10px",
            border: "1px solid var(--border-32)",
            borderRadius: 2,
            background: "transparent",
            color: "var(--t-85)",
            cursor: "pointer",
            fontFamily: "inherit",
            fontSize: 11,
          }}
        >
          SIGN IN
        </button>
        {dialogOpen && <SignInDialog onClose={() => setDialogOpen(false)} />}
      </>
    );
  }

  const label = user?.username ?? user?.email ?? "account";
  return (
    <div
      ref={wrapRef}
      style={{ position: "relative" }}
      onMouseEnter={() => setMenuOpen(true)}
      onMouseLeave={() => setMenuOpen(false)}
    >
      <span
        style={{ color: "var(--accent)", cursor: "default", fontSize: 11 }}
        title={user?.email ?? label}
      >
        {label}
      </span>
      {menuOpen && (
        <div style={{ position: "absolute", right: 0, top: "100%", paddingTop: 8, zIndex: 60 }}>
        <div
          role="menu"
          style={{
            background: "var(--panel-2)",
            border: "1px solid var(--border-30)",
            padding: "10px 12px",
            width: 190,
            boxShadow: "0 8px 20px rgba(0,0,0,0.5)",
          }}
        >
          <div style={{ fontSize: 11, color: "var(--t-80)", marginBottom: 8, lineHeight: 1.4 }}>
            Sign out of this session?
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                void signOut();
              }}
              style={{
                flex: 1,
                padding: "4px 0",
                border: "1px solid var(--border-32)",
                borderRadius: 2,
                background: "transparent",
                color: "var(--t-85)",
                cursor: "pointer",
                fontSize: 10.5,
                fontFamily: "inherit",
              }}
            >
              SIGN OUT
            </button>
            <button
              type="button"
              onClick={() => setMenuOpen(false)}
              style={{
                flex: 1,
                padding: "4px 0",
                border: "none",
                borderRadius: 2,
                background: "var(--panel-active)",
                color: "var(--t-85)",
                cursor: "pointer",
                fontSize: 10.5,
                fontFamily: "inherit",
              }}
            >
              CANCEL
            </button>
          </div>
        </div>
        </div>
      )}
    </div>
  );
}

export function AppHeader({
  activeTab,
  onTabChange,
  filter,
  onFilterChange,
  marketSessionActive,
  marketPhase,
  gatewayState = "CONNECTED",
  upstreamFeedState = marketSessionActive ? "CONNECTED" : "UNKNOWN",
  searchOptions = [],
  onJump,
}: AppHeaderProps) {
  const [draft, setDraft] = useState(filter);
  const [searchOpen, setSearchOpen] = useState(false);
  const [activeResult, setActiveResult] = useState(0);
  useEffect(() => setDraft(filter), [filter]);
  const matches = useMemo(() => {
    const term = draft.trim().toUpperCase();
    if (!term) return [];
    const order: Record<Tab, number> = { dashboard: 0, research: 1, news: 2 };
    return searchOptions.filter(option => option.symbol.startsWith(term))
      .sort((a, b) => a.symbol.localeCompare(b.symbol) || order[a.destination] - order[b.destination]);
  }, [draft, searchOptions]);
  const jump = (option: GlobalSearchOption) => {
    setDraft(option.symbol); setSearchOpen(false); onJump?.(option);
  };
  const sessionLabel = ({ PRE_OPEN: "PRE-OPEN", ATO: "ATO", LUNCH_BREAK: "LUNCH BREAK",
    ATC: "ATC", POST_CLOSE_NEGOTIATED: "NEGOTIATED", CLOSED: "CLOSED", UNKNOWN: "SYNCING" } as Record<string, string>)[marketPhase ?? ""]
    ?? (marketSessionActive ? "OPEN" : "CLOSED");
  // Exception-only feed status. A healthy feed shows nothing: the session chip beside it
  // already reads OPEN with a green dot, so a second "LIVE" badge was pure duplication.
  // The abnormal states stay - on a trading terminal, silently hiding STALE / RECONNECTING
  // / OFFLINE would be the dangerous edit, since those are exactly when the numbers lie.
  const feedLabel = gatewayState === "RECONNECTING" || upstreamFeedState === "RECONNECTING"
      ? "RECONNECTING"
      : upstreamFeedState === "STALE"
        ? "STALE"
        : gatewayState === "ERROR" || gatewayState === "DISCONNECTED" || upstreamFeedState === "DISCONNECTED" || upstreamFeedState === "ERROR"
          ? "OFFLINE"
          : upstreamFeedState === "CONNECTED"
            ? null
            : "CONNECTING";
  const feedTone = feedLabel === "STALE" || feedLabel === "RECONNECTING" || feedLabel === "CONNECTING"
    ? "var(--flat)"
    : "var(--t-46)";

  return (
    <header
      className="terminal-header"
      style={{
        borderBottom: "1px solid var(--border-strong)",
        flexShrink: 0,
        background: "var(--bg)",
      }}
    >
      <div className="terminal-header-start">
        <span
          className="heading"
          style={{ fontSize: 12, fontWeight: 700, letterSpacing: "0.04em", color: "var(--accent)" }}
        >
          CW-TERMINAL
        </span>

        <div style={{ display: "flex", gap: 2, background: "var(--panel-2)", padding: 2, borderRadius: 3 }}>
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => onTabChange(t.id)}
              className="focus-ring"
              aria-pressed={activeTab === t.id}
              style={{
                ...TAB_BASE,
                background: activeTab === t.id ? "var(--panel-active)" : "transparent",
                color: activeTab === t.id ? "var(--t-92)" : "var(--t-55)",
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="terminal-header-search" onBlur={event => {
        if (!event.currentTarget.contains(event.relatedTarget as Node)) setSearchOpen(false);
      }}>
        <input value={draft} onChange={(e) => { setDraft(e.target.value); setSearchOpen(!!e.target.value.trim()); setActiveResult(0); }}
          onKeyDown={(e) => {
            if (e.nativeEvent.isComposing) return;
            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
              if (!matches.length) return;
              e.preventDefault(); setSearchOpen(true);
              setActiveResult(index => Math.max(0, Math.min(matches.length - 1, index + (e.key === "ArrowDown" ? 1 : -1))));
            }
            if (e.key === "Enter") {
              e.preventDefault();
              if (searchOpen && matches[activeResult]) jump(matches[activeResult]);
              else { const query = e.currentTarget.value.trim(); setDraft(query); setSearchOpen(false); onFilterChange(query); }
            }
            if (e.key === "Escape") { e.preventDefault(); setDraft(filter); setSearchOpen(false); }
          }}
          placeholder="/ filter or jump to symbol" aria-label="Filter or jump to symbol" aria-expanded={searchOpen && matches.length > 0}
          aria-controls={searchOpen && matches.length ? "global-search-results" : undefined} className="focus-ring" />
        {searchOpen && matches.length > 0 && <div id="global-search-results" className="global-search-results" role="listbox" aria-label="Global symbol destinations">
          {matches.map((option, index) => <button type="button" role="option" aria-selected={index === activeResult}
            key={`${option.symbol}:${option.destination}`} onMouseDown={event => event.preventDefault()} onClick={() => jump(option)}>
            <span>{option.symbol}</span><span>{option.kind === "cw" ? "CW" : option.kind === "stock" ? "STOCK" : "NEWS"}</span>
            <strong>{option.destination === "dashboard" ? "WATCHLIST" : option.destination.toUpperCase()}</strong>
          </button>)}
        </div>}
      </div>

      <div
        className="terminal-header-end"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 18,
          fontSize: 11,
          color: "var(--t-66)",
        }}
      >
        <HeaderClock />
        <span aria-label={`Market session ${sessionLabel.toLowerCase()}`} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              width: 6,
              height: 6,
              background: marketSessionActive ? "var(--up)" : "var(--t-46)",
            }}
            aria-hidden
          />
          {sessionLabel}
        </span>
        {feedLabel && <span aria-label={`Market feed ${feedLabel.toLowerCase()}`} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 6, height: 6, background: feedTone }} aria-hidden />
          {feedLabel}
        </span>}
        <FeedNotice />
        <SignInControl />
      </div>
    </header>
  );
}
