import { useEffect, useState } from "react";
import { useAuth, isGoogleAuthEnabled } from "@/data/auth";

type Mode = "signin" | "signup";

/**
 * Sign-in / create-account popover. Three explicit paths: Google (when configured),
 * email+password (sign in or create account, via tabs), and Continue as Guest - the
 * dashboard already works fully anonymously, so guest is just closing the dialog. The
 * magic-link flow doesn't go away: it's the "Or email me a sign-in link" fallback under
 * the Sign in tab, for a Google-only or not-yet-set-a-password account. Not a route, not
 * a wall: the dashboard stays mounted behind it.
 */
export function SignInDialog({ onClose }: { onClose: () => void }) {
  const { signInWithGoogle, signInWithEmail, signUpWithPassword, signInWithPassword } = useAuth();
  const googleEnabled = isGoogleAuthEnabled();
  const [mode, setMode] = useState<Mode>("signin");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const switchMode = (next: Mode) => {
    setMode(next);
    setMessage(null);
  };

  const submitPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    const res =
      mode === "signup"
        ? await signUpWithPassword(username, email, password)
        : await signInWithPassword(email, password);
    setMessage({ ok: res.ok, text: res.message });
    setBusy(false);
  };

  const sendMagicLink = async () => {
    setBusy(true);
    setMessage(null);
    const res = await signInWithEmail(email);
    setMessage({ ok: res.ok, text: res.message });
    setBusy(false);
  };

  const field: React.CSSProperties = {
    width: "100%",
    boxSizing: "border-box",
    padding: "8px 10px",
    borderRadius: 3,
    border: "1px solid var(--border-strong)",
    background: "var(--panel-2)",
    color: "var(--t-92)",
    fontFamily: "var(--font-mono)",
    fontSize: 12,
    outline: "none",
  };

  const primaryBtn: React.CSSProperties = {
    padding: "8px 12px",
    borderRadius: 3,
    border: "1px solid var(--border-strong)",
    background: "var(--panel-active)",
    color: "var(--t-92)",
    fontSize: 11,
    letterSpacing: "0.06em",
    textTransform: "uppercase",
    cursor: busy ? "default" : "pointer",
    opacity: busy ? 0.6 : 1,
  };

  const tabBtn = (active: boolean): React.CSSProperties => ({
    flex: 1,
    padding: "7px 0",
    border: "none",
    borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
    background: "transparent",
    color: active ? "var(--t-92)" : "var(--t-55)",
    fontSize: 11,
    letterSpacing: "0.06em",
    textTransform: "uppercase",
    cursor: "pointer",
    fontFamily: "inherit",
  });

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={mode === "signup" ? "Create account" : "Sign in"}
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 60,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
        // The control mounts inside `.terminal-header-end`, which sets
        // `white-space: nowrap`; reset it or the copy never wraps.
        whiteSpace: "normal",
        background: "rgba(2, 6, 12, 0.55)",
        backdropFilter: "blur(2px)",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%",
          maxWidth: 340,
          boxSizing: "border-box",
          border: "1px solid var(--border-strong)",
          background: "var(--panel)",
          padding: 20,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div
          className="heading"
          style={{ fontSize: 13, fontWeight: 700, letterSpacing: "0.06em", color: "var(--t-92)" }}
        >
          {mode === "signup" ? "Create account" : "Sign in"}
        </div>
        <p className="mono" style={{ fontSize: 11, lineHeight: 1.6, color: "var(--t-55)", margin: 0 }}>
          Sign in to sync your watchlist and get a larger AI research allowance. Everything
          else stays open either way.
        </p>

        {googleEnabled && (
          <>
            <button
              type="button"
              onClick={() => void signInWithGoogle()}
              className="heading focus-ring"
              style={{
                padding: "8px 12px",
                borderRadius: 3,
                border: "1px solid var(--border-strong)",
                background: "var(--panel-2)",
                color: "var(--t-92)",
                fontSize: 11,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                cursor: "pointer",
              }}
            >
              Continue with Google
            </button>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ flex: 1, height: 1, background: "var(--border)" }} />
              <span className="mono" style={{ fontSize: 9, color: "var(--t-46)" }}>OR</span>
              <span style={{ flex: 1, height: 1, background: "var(--border)" }} />
            </div>
          </>
        )}

        <div style={{ display: "flex", borderBottom: "1px solid var(--border)" }}>
          <button type="button" onClick={() => switchMode("signin")} style={tabBtn(mode === "signin")}>
            Sign in
          </button>
          <button type="button" onClick={() => switchMode("signup")} style={tabBtn(mode === "signup")}>
            Create account
          </button>
        </div>

        <form onSubmit={submitPassword} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {mode === "signup" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <input
                type="text"
                required
                placeholder="Username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                minLength={3}
                maxLength={32}
                pattern="[A-Za-z0-9_]+"
                style={field}
              />
            </div>
          )}
          <input
            type="email"
            required
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={field}
          />
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <input
              type="password"
              required
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={mode === "signup" ? 8 : undefined}
              autoComplete={mode === "signup" ? "new-password" : "current-password"}
              style={field}
            />
            {mode === "signup" && (
              <span className="mono" style={{ fontSize: 9.5, color: "var(--t-46)" }}>
                At least 8 characters
              </span>
            )}
          </div>
          <button type="submit" disabled={busy} className="heading focus-ring" style={primaryBtn}>
            {busy ? "Please wait…" : mode === "signup" ? "Create account" : "Sign in"}
          </button>
          {mode === "signin" && (
            <button
              type="button"
              onClick={() => void sendMagicLink()}
              disabled={busy}
              className="mono"
              style={{
                background: "none",
                border: "none",
                padding: 0,
                color: "var(--t-55)",
                fontSize: 10.5,
                textAlign: "center",
                cursor: busy ? "default" : "pointer",
                textDecoration: "underline",
                textUnderlineOffset: 2,
              }}
            >
              Or email me a sign-in link
            </button>
          )}
        </form>

        {message && (
          <p
            className="mono"
            style={{ margin: 0, fontSize: 11, lineHeight: 1.5, color: message.ok ? "var(--up)" : "var(--down)" }}
          >
            {message.text}
          </p>
        )}

        <button
          type="button"
          onClick={onClose}
          className="mono focus-ring"
          style={{
            padding: "8px 12px",
            borderRadius: 3,
            border: "1px solid transparent",
            background: "transparent",
            color: "var(--t-55)",
            fontSize: 11,
            letterSpacing: "0.02em",
            cursor: "pointer",
          }}
        >
          Continue as Guest →
        </button>
      </div>
    </div>
  );
}
