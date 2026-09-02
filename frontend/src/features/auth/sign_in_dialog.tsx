import { useRef, useState } from "react";
import { X } from "lucide-react";
import { useAuth, isGoogleAuthEnabled } from "@/data/auth";
import { useDialogFocus } from "@/components/common/ui";

export function SignInDialog({ onClose }: { onClose: () => void }) {
  const { signInWithGoogle, signInWithEmail } = useAuth();
  const ref = useRef<HTMLDivElement>(null);
  useDialogFocus(ref, onClose);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const submit = async (google = false) => {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    try {
      if (google) {
        await signInWithGoogle();
        return;
      }
      const result = await signInWithEmail(email.trim());
      setMessage({
        ok: result.ok,
        text:
          result.ok && !google
            ? `Check ${email.trim()} for your sign-in link. You can close this window and keep researching.`
            : result.message,
      });
    } catch {
      setMessage({
        ok: false,
        text: "Could not send your request. Please try again.",
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div
      className="dialog-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={ref}
        className="sign-in-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="sign-in-title"
      >
        <div className="section-toolbar">
          <h2 id="sign-in-title">Sign in</h2>
          <button
            className="icon-btn"
            onClick={onClose}
            aria-label="Close sign in"
          >
            <X size={18} />
          </button>
        </div>
        <p>
          Keep your watchlist across devices. Market data and research are also
          available without an account.
        </p>
        {isGoogleAuthEnabled() && (
          <button
            className="btn"
            disabled={busy}
            onClick={() => void submit(true)}
          >
            Continue with Google
          </button>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <label className="field-label" htmlFor="sign-in-email">
            Email
          </label>
          <input
            id="sign-in-email"
            name="email"
            type="email"
            autoComplete="email"
            required
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={busy}
          />
          <button className="btn btn-accent" type="submit" disabled={busy}>
            {busy ? "Sending…" : "Email me a sign-in link"}
          </button>
        </form>
        {message && (
          <p
            role={message.ok ? "status" : "alert"}
            style={{ color: message.ok ? "var(--up)" : "var(--down)" }}
          >
            {message.text}
          </p>
        )}
      </div>
    </div>
  );
}
