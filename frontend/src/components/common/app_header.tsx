import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/data/auth";
import { SignInDialog } from "@/features/auth/sign_in_dialog";

type Tab = "dashboard" | "research";

interface AppHeaderProps {
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
  filter: string;
  onFilterChange: (value: string) => void;
  marketSessionActive: boolean;
}

const VN_TZ = "Asia/Ho_Chi_Minh";

/** "Aug 29, 2026 · 10:15 ICT" in Vietnam local time. */
function useVietnamClock(): string {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 15_000);
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
    hour12: false,
  }).format(d);
  return `${date} · ${time} ICT`;
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
        <div
          role="menu"
          style={{
            position: "absolute",
            right: 0,
            top: "100%",
            marginTop: 8,
            zIndex: 60,
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
  const clock = useVietnamClock();

  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        padding: "0 20px",
        height: 42,
        borderBottom: "1px solid var(--border-strong)",
        flexShrink: 0,
        background: "var(--bg)",
      }}
    >
      <span
        className="heading"
        style={{ fontSize: 12, fontWeight: 700, letterSpacing: "0.04em", color: "var(--accent)" }}
      >
        CW-TERM
      </span>

      <div style={{ display: "flex", gap: 2, background: "var(--panel-2)", padding: 2, borderRadius: 3 }}>
        <button
          type="button"
          onClick={() => onTabChange("dashboard")}
          className="focus-ring"
          aria-pressed={activeTab === "dashboard"}
          style={{
            ...TAB_BASE,
            background: activeTab === "dashboard" ? "var(--panel-active)" : "transparent",
            color: activeTab === "dashboard" ? "var(--t-92)" : "var(--t-55)",
          }}
        >
          DASHBOARD
        </button>
        <button
          type="button"
          onClick={() => onTabChange("research")}
          className="focus-ring"
          aria-pressed={activeTab === "research"}
          style={{
            ...TAB_BASE,
            background: activeTab === "research" ? "var(--panel-active)" : "transparent",
            color: activeTab === "research" ? "var(--t-92)" : "var(--t-55)",
          }}
        >
          RESEARCH
        </button>
      </div>

      <input
        value={filter}
        onChange={(e) => onFilterChange(e.target.value)}
        placeholder="/ filter or jump to symbol"
        aria-label="Filter or jump to symbol"
        className="focus-ring"
        style={{
          flex: 1,
          maxWidth: 320,
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
        style={{
          marginLeft: "auto",
          display: "flex",
          alignItems: "center",
          gap: 18,
          fontSize: 11,
          color: "var(--t-66)",
        }}
      >
        <span className="mono">{clock}</span>
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
