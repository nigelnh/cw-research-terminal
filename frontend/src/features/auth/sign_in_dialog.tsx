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
        background: "rgba(2, 6, 12, 0.55)",
        backdropFilter: "blur(2px)",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "320px",
          borderRadius: "10px",
          border: "1px solid var(--border-strong)",
          background: "var(--background)",
          padding: "22px",
          display: "flex",
          flexDirection: "column",
          gap: "14px",
        }}
      >
        <div style={{ fontSize: "14px", fontWeight: 600, color: "var(--foreground)" }}>Sign in</div>
        <p style={{ fontSize: "12px", color: "var(--muted-foreground)", margin: 0, lineHeight: 1.5 }}>
          Sign in only to keep your watchlist across devices. The dashboard, research and market
          data stay open either way.
        </p>

        {googleEnabled && (
          <>
            <button
              type="button"
              onClick={() => void signInWithGoogle()}
              className="focus-ring"
              style={{
                padding: "9px 12px",
                borderRadius: "6px",
                border: "1px solid var(--border-strong)",
                background: "var(--card)",
                color: "var(--foreground)",
                fontSize: "13px",
                cursor: "pointer",
              }}
            >
              Continue with Google
            </button>

            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ flex: 1, height: "1px", background: "var(--border)" }} />
              <span style={{ fontSize: "10px", color: "var(--muted-foreground)" }}>OR</span>
              <span style={{ flex: 1, height: "1px", background: "var(--border)" }} />
            </div>
          </>
        )}

        <form onSubmit={submitEmail} style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          <input
            type="email"
            required
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={{
              padding: "9px 12px",
              borderRadius: "6px",
              border: "1px solid var(--border-strong)",
              background: "var(--input, var(--card))",
              color: "var(--foreground)",
              fontSize: "13px",
            }}
          />
          <button
            type="submit"
            disabled={busy}
            className="focus-ring"
            style={{
              padding: "9px 12px",
              borderRadius: "6px",
              border: "1px solid var(--primary)",
              background: "transparent",
              color: "var(--primary)",
              fontSize: "13px",
              cursor: busy ? "default" : "pointer",
              opacity: busy ? 0.6 : 1,
            }}
          >
            {busy ? "Sending…" : "Email me a sign-in link"}
          </button>
        </form>

        {message && (
          <p
            style={{
              margin: 0,
              fontSize: "12px",
              color: message.ok ? "var(--up)" : "var(--destructive)",
            }}
          >
            {message.text}
          </p>
        )}
      </div>
    </div>
  );
}
