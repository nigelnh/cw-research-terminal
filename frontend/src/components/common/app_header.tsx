import { useEffect, useId, useRef, useState } from "react";
import { Search, UserRound } from "lucide-react";
import { useAuth } from "@/data/auth";
import { SignInDialog } from "@/features/auth/sign_in_dialog";
import { Popover } from "./ui";

type Tab = "dashboard" | "research" | "news";
interface Props {
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
  marketSessionActive: boolean;
  marketSession?: string;
  connectionState?: string;
  symbols?: string[];
  onSelectSymbol?: (symbol: string) => void;
  filter?: string;
  onFilterChange?: (value: string) => void;
}
function HeaderClock() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const d = new Date(now);
  const date = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Ho_Chi_Minh",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(d);
  const time = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Ho_Chi_Minh",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(d);
  return (
    <time className="header-clock mono" dateTime={d.toISOString()}>
      <span className="header-date">{date} · </span>
      {time} ICT
    </time>
  );
}
function SignInControl() {
  const { user, status, isConfigured, signOut } = useAuth();
  const [dialogOpen, setDialogOpen] = useState(false);
  if (!isConfigured) return null;
  if (status === "loading") return <span className="muted">…</span>;
  return (
    <>
      {status === "anonymous" ? (
        <button
          className="btn header-signin"
          onClick={() => setDialogOpen(true)}
        >
          Sign in
        </button>
      ) : (
        <Popover label="Account" width={270} icon={<UserRound size={16} />}>
          <div className="account-menu">
            <span>{user?.email}</span>
            <p className="section-subtitle">
              Your watchlist is synced across devices.
            </p>
            <button className="btn" onClick={() => void signOut()}>
              Sign out
            </button>
          </div>
        </Popover>
      )}
      {dialogOpen && <SignInDialog onClose={() => setDialogOpen(false)} />}
    </>
  );
}
export function AppHeader({
  activeTab,
  onTabChange,
  marketSessionActive,
  marketSession,
  connectionState,
  symbols = [],
  onSelectSymbol,
}: Props) {
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const ref = useRef<HTMLInputElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const listId = useId();
  const clean = term.trim().toUpperCase();
  const matches = clean
    ? symbols
        .filter((s) => s.includes(clean))
        .sort(
          (a, b) =>
            Number(!a.startsWith(clean)) - Number(!b.startsWith(clean)) ||
            a.localeCompare(b),
        )
        .slice(0, 8)
    : [];
  const select = (symbol: string) => {
    onSelectSymbol?.(symbol);
    setTerm("");
    setOpen(false);
    ref.current?.blur();
  };
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (document.querySelector('[aria-modal="true"]')) return;
      if (
        e.key === "/" &&
        !target.closest("input,textarea,select,[contenteditable=true]")
      ) {
        e.preventDefault();
        ref.current?.focus();
        setOpen(true);
      }
    };
    const outside = (e: PointerEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", key);
    document.addEventListener("pointerdown", outside);
    return () => {
      document.removeEventListener("keydown", key);
      document.removeEventListener("pointerdown", outside);
    };
  }, []);
  const feedIssue = [
    "ERROR",
    "DISCONNECTED",
    "RECONNECTING",
    "CONNECTING",
  ].includes(connectionState ?? "");
  const marketLabel = marketSessionActive
    ? "Session open"
    : marketSession === "LUNCH_BREAK"
      ? "Lunch break"
      : "Market closed";
  return (
    <header className="app-header">
      <span className="brand">CW-TERMINAL</span>
      <nav aria-label="Main navigation" className="main-nav">
        {(["dashboard", "research", "news"] as const).map((tab) => (
          <button
            key={tab}
            className={activeTab === tab ? "active" : ""}
            aria-pressed={activeTab === tab}
            onClick={() => onTabChange(tab)}
          >
            {tab.toUpperCase()}
          </button>
        ))}
      </nav>
      <div className="symbol-search" ref={wrap}>
        <Search size={14} aria-hidden="true" />
        <input
          ref={ref}
          role="combobox"
          aria-label="Jump to symbol"
          aria-autocomplete="list"
          aria-expanded={open && !!clean}
          aria-controls={listId}
          aria-activedescendant={
            open && matches[index] ? `${listId}-${index}` : undefined
          }
          placeholder="Jump to symbol…"
          value={term}
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setTerm(e.target.value);
            setIndex(0);
            setOpen(true);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setOpen(false);
              setTerm("");
            } else if (e.key === "ArrowDown") {
              e.preventDefault();
              setOpen(true);
              setIndex((i) => Math.min(i + 1, matches.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setIndex((i) => Math.max(0, i - 1));
            } else if (e.key === "Enter" && matches[index]) {
              e.preventDefault();
              select(matches[index]);
            }
          }}
        />
        <kbd>/</kbd>
        {open && clean && (
          <div id={listId} className="symbol-results" role="listbox">
            {matches.length ? (
              matches.map((symbol, i) => (
                <button
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={index === i}
                  key={symbol}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => select(symbol)}
                >
                  <span className="mono">{symbol}</span>
                  <span>Inspect ↵</span>
                </button>
              ))
            ) : (
              <p>No matching symbol</p>
            )}
          </div>
        )}
      </div>
      <div className="header-status">
        <HeaderClock />
        <span className={`data-status ${marketSessionActive ? "live" : ""}`}>
          {marketLabel}
        </span>
        {feedIssue && (
          <span className="badge badge-warning">
            {connectionState === "RECONNECTING" ||
            connectionState === "CONNECTING"
              ? "Connecting"
              : "Backend offline"}
          </span>
        )}
      </div>
      <SignInControl />
    </header>
  );
}
