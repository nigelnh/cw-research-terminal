import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/data/auth";
import { SignInDialog } from "@/features/auth/sign_in_dialog";

type Tab = "dashboard" | "research" | "news";

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
}

const VN_TZ = "Asia/Ho_Chi_Minh";

/**
 * "Aug 29, 2026 · 21:43:07 ICT" in Vietnam local time. Its own component + interval so
 * the once-per-second tick re-renders only this span, not the whole header.
 */
function HeaderClock() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
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

  const label = user?.email ?? "account";
  return (
    <div
      ref={wrapRef}
      style={{ position: "relative" }}
      onMouseEnter={() => setMenuOpen(true)}
      onMouseLeave={() => setMenuOpen(false)}
    >
      <span
        style={{ color: "var(--accent)", cursor: "default", fontSize: 11 }}
        title={label}
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
}: AppHeaderProps) {
  const [draft, setDraft] = useState(filter);
  useEffect(() => setDraft(filter), [filter]);

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

      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.nativeEvent.isComposing) return;
          if (e.key === "Enter") {
            e.preventDefault();
            const query = e.currentTarget.value.trim();
            setDraft(query);
            onFilterChange(query);
          }
          if (e.key === "Escape") { e.preventDefault(); setDraft(filter); }
        }}
        placeholder="/ filter or jump to symbol"
        aria-label="Filter or jump to symbol"
        className="focus-ring terminal-header-search"
        style={{
          background: "var(--panel-2)",
          border: "1px solid var(--border-strong)",
          borderRadius: 3,
          padding: "5px 10px",
          fontFamily: "inherit",
          fontSize: 11,
          color: "var(--t-92)",
          outline: "none",
        }}
      />

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
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              width: 6,
              height: 6,
              background: marketSessionActive ? "var(--up)" : "var(--t-46)",
            }}
            aria-hidden
          />
          {marketSessionActive ? "LIVE" : "CLOSED"}
        </span>
        <SignInControl />
      </div>
    </header>
  );
}
