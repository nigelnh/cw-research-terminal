import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/data/auth";
import { SignInDialog } from "./sign_in_dialog";

/**
 * The single auth control in the top nav. Renders nothing on an anonymous-only build
 * (no Supabase config). Anonymous -> "Sign in". Authenticated -> a small account menu
 * with "Sign out". No navigation redesign, no login wall.
 */
export function AccountMenu() {
  const { user, status, isConfigured, signOut } = useAuth();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [menuOpen]);

  if (!isConfigured) return null;

  if (status === "loading") {
    return <span style={{ fontSize: "12px", color: "var(--muted-foreground)" }} aria-hidden>·</span>;
  }

  if (status === "anonymous") {
    return (
      <>
        <button
          type="button"
          onClick={() => setDialogOpen(true)}
          className="focus-ring"
          style={{
            padding: "6px 12px",
            borderRadius: "6px",
            border: "1px solid var(--border-strong)",
            background: "transparent",
            color: "var(--foreground)",
            fontSize: "12px",
            cursor: "pointer",
          }}
        >
          Sign in
        </button>
        {dialogOpen && <SignInDialog onClose={() => setDialogOpen(false)} />}
      </>
    );
  }

  const label = user?.email ?? "Account";
  const initial = (user?.email ?? "?").slice(0, 1).toUpperCase();

  return (
    <div ref={menuRef} style={{ position: "relative" }}>
      <button
        type="button"
        onClick={() => setMenuOpen((o) => !o)}
        className="focus-ring"
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        title={label}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "26px",
          width: "26px",
          borderRadius: "50%",
          border: "1px solid var(--border-strong)",
          background: "var(--card)",
          color: "var(--foreground)",
          fontSize: "11px",
          fontWeight: 600,
          cursor: "pointer",
        }}
      >
        {initial}
      </button>

      {menuOpen && (
        <div
          role="menu"
          style={{
            position: "absolute",
            right: 0,
            top: "34px",
            minWidth: "200px",
            borderRadius: "8px",
            border: "1px solid var(--border-strong)",
            background: "var(--background)",
            padding: "8px",
            display: "flex",
            flexDirection: "column",
            gap: "4px",
            zIndex: 50,
          }}
        >
          <div
            style={{
              padding: "6px 8px",
              fontSize: "11px",
              color: "var(--muted-foreground)",
              wordBreak: "break-all",
            }}
          >
            {label}
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenuOpen(false);
              void signOut();
            }}
            style={{
              textAlign: "left",
              padding: "7px 8px",
              borderRadius: "5px",
              border: "none",
              background: "transparent",
              color: "var(--foreground)",
              fontSize: "12px",
              cursor: "pointer",
            }}
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
