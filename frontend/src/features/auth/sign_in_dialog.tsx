import { useEffect, useState } from "react";
import { useAuth, isGoogleAuthEnabled } from "@/data/auth";

/**
 * Compact sign-in popover. Email magic link always; Google OAuth only when the provider
 * is configured (VITE_AUTH_GOOGLE_ENABLED). No password field - the provider owns
 * credentials. Not a route, not a wall: the dashboard stays mounted behind it.
 */
export function SignInDialog({ onClose }: { onClose: () => void }) {
  const { signInWithGoogle, signInWithEmail } = useAuth();
  const googleEnabled = isGoogleAuthEnabled();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submitEmail = async (e: React.FormEvent) => {
    e.preventDefault();
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

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Sign in"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 60,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
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
          Sign in
        </div>
        <p
          className="mono"
          style={{
            fontSize: 11,
            lineHeight: 1.6,
            color: "var(--t-55)",
            margin: 0,
          }}
        >
          Sign in only to keep your watchlist across devices. The dashboard, research and
          market data stay open either way.
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

        <form onSubmit={submitEmail} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <input
            type="email"
            required
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={field}
          />
          <button
            type="submit"
            disabled={busy}
            className="heading focus-ring"
            style={{
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
            }}
          >
            {busy ? "Sending…" : "Email me a sign-in link"}
          </button>
        </form>

        {message && (
          <p
            className="mono"
            style={{
              margin: 0,
              fontSize: 11,
              lineHeight: 1.5,
              color: message.ok ? "var(--up)" : "var(--down)",
            }}
          >
            {message.text}
          </p>
        )}
      </div>
    </div>
  );
}
