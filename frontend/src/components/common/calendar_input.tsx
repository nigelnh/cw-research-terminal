import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useFixedPopover } from "./filter_popover";

/**
 * Grid Terminal date picker: an editable mm/dd/yyyy field + a
 * calendar popover (‹ MONTH YYYY ›, a 6-week day grid). Replaces the browser's
 * native date input so every filter reads the same in the terminal.
 *
 * `value` / `onChange` are ISO `yyyy-mm-dd` (or "" for empty) so callers can string-
 * compare against ISO row dates; the field only *displays* mm/dd/yyyy.
 */

const MONTHS = [
  "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
  "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
];

function isoToDisplay(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  return m ? `${m[2]}/${m[3]}/${m[1]}` : "";
}
function toIso(y: number, m: number, d: number): string {
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

export function maskDateInput(text: string): string {
  const digits = text.replace(/\D/g, "").slice(0, 8);
  return [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4)].filter(Boolean).join("/");
}

function displayToIso(text: string): string | null {
  if (!text) return "";
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(text);
  if (!match) return null;
  const [, mm, dd, yyyy] = match;
  const y = Number(yyyy), m = Number(mm), d = Number(dd);
  const date = new Date(y, m - 1, d);
  return y >= 1900 && date.getFullYear() === y && date.getMonth() === m - 1 && date.getDate() === d
    ? toIso(y, m, d) : null;
}

export function CalendarInput({
  value,
  onChange,
  ariaLabel,
  resetKey,
}: {
  value: string;
  onChange: (isoOrEmpty: string) => void;
  ariaLabel: string;
  resetKey?: number;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(() => isoToDisplay(value));
  const [invalid, setInvalid] = useState(false);
  const errorId = useId();
  useEffect(() => { setDraft(isoToDisplay(value)); setInvalid(false); }, [value, resetKey]);
  const [ym, setYm] = useState<{ y: number; m: number }>(() => {
    const m = /^(\d{4})-(\d{2})-/.exec(value);
    if (m) return { y: Number(m[1]), m: Number(m[2]) };
    const now = new Date();
    return { y: now.getFullYear(), m: now.getMonth() + 1 };
  });
  const boxRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const calendarRef = useRef<HTMLDivElement | null>(null);
  const position = useFixedPopover(open, boxRef, calendarRef, 202);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: PointerEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDoc);
    return () => {
      document.removeEventListener("pointerdown", onDoc);
    };
  }, [open]);

  const cells = useMemo(() => {
    const first = new Date(ym.y, ym.m - 1, 1).getDay(); // 0=Sun
    const days = new Date(ym.y, ym.m, 0).getDate();
    const out: (number | null)[] = [];
    for (let i = 0; i < first; i++) out.push(null);
    for (let d = 1; d <= days; d++) out.push(d);
    while (out.length < 42) out.push(null);
    return out;
  }, [ym]);

  const step = (delta: number) => {
    let { y, m } = ym;
    m += delta;
    if (m < 1) { m = 12; y--; }
    if (m > 12) { m = 1; y++; }
    setYm({ y, m });
  };

  const selDay = (() => {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    return m && Number(m[1]) === ym.y && Number(m[2]) === ym.m ? Number(m[3]) : null;
  })();

  return (
    <div ref={boxRef} style={{ position: "relative", flex: "1 1 0", minWidth: 0 }}
      onKeyDown={(e) => {
        if (open && e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          setOpen(false);
          inputRef.current?.focus({ preventScroll: true });
        }
      }}>
      <input
        ref={inputRef}
        type="text"
        aria-label={ariaLabel}
        aria-invalid={invalid || undefined}
        aria-describedby={invalid ? errorId : undefined}
        inputMode="numeric"
        maxLength={10}
        value={draft}
        placeholder="mm/dd/yyyy"
        onClick={() => setOpen(false)}
        onChange={(e) => {
          const input = e.target;
          const digitsBeforeCaret = input.value.slice(0, input.selectionStart ?? input.value.length).replace(/\D/g, "").length;
          const next = maskDateInput(input.value);
          setDraft(next);
          setInvalid(false);
          const iso = displayToIso(next);
          if (iso !== null) onChange(iso);
          // Preserve the editing position when the mask inserts/removes a slash.
          const caret = Math.min(next.length, digitsBeforeCaret + (digitsBeforeCaret > 2 ? 1 : 0) + (digitsBeforeCaret > 4 ? 1 : 0));
          requestAnimationFrame(() => input.setSelectionRange(caret, caret));
        }}
        onBlur={() => setInvalid(displayToIso(draft) === null)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            const iso = displayToIso(draft);
            setInvalid(iso === null);
            if (iso !== null) onChange(iso);
          }
          if ((e.key === "Backspace" || e.key === "Delete") && e.currentTarget.selectionStart === e.currentTarget.selectionEnd) {
            const caret = e.currentTarget.selectionStart ?? 0;
            const adjacent = e.key === "Backspace" ? caret - 1 : caret;
            if (draft[adjacent] === "/") {
              e.preventDefault();
              const nextCaret = e.key === "Backspace" ? caret - 1 : caret + 1;
              e.currentTarget.setSelectionRange(nextCaret, nextCaret);
            }
          }
        }}
        style={{
          width: "100%",
          background: "var(--bg)",
          border: "1px solid var(--border-26)",
          padding: "4px 38px 4px 8px",
          minWidth: 0,
          height: 28,
          boxSizing: "border-box",
          fontSize: 11,
          color: "var(--t-85)",
          fontFamily: "inherit",
          outline: "none",
          cursor: "text",
        }}
      />
      <button
        type="button"
        onClick={() => {
          const iso = displayToIso(draft) || value;
          if (iso) setYm({ y: Number(iso.slice(0, 4)), m: Number(iso.slice(5, 7)) });
          setOpen((o) => !o);
        }}
        title="Pick date"
        aria-label={`${ariaLabel} — open calendar`}
        aria-expanded={open}
        aria-haspopup="dialog"
        style={{
          position: "absolute",
          right: 4,
          top: "50%",
          transform: "translateY(-50%)",
          background: "none",
          border: "none",
          cursor: "pointer",
          color: "var(--t-55)",
          padding: 2,
          display: "flex",
        }}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <rect x="3" y="5" width="18" height="16" rx="2" />
          <path d="M3 10h18M8 3v4M16 3v4" />
        </svg>
      </button>
      {draft && (
        <button
          type="button"
          onClick={() => { setDraft(""); setInvalid(false); onChange(""); inputRef.current?.focus({ preventScroll: true }); }}
          title="Clear date"
          aria-label={`${ariaLabel} — clear`}
          style={{
            position: "absolute",
            right: 22,
            top: "50%",
            transform: "translateY(-50%)",
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "var(--t-42)",
            padding: 0,
            fontSize: 11,
            lineHeight: 1,
          }}
        >
          ×
        </button>
      )}
      {invalid && <span id={errorId} role="alert" style={{ display: "block", fontSize: 10, color: "var(--down)", marginTop: 4 }}>Enter a valid date: mm/dd/yyyy.</span>}
      {open && (
        <div
          ref={calendarRef}
          role="dialog"
          aria-label={`${ariaLabel} calendar`}
          className="calendar-popover"
          style={{
            ...position,
            zIndex: 70,
            background: "var(--panel-2)",
            border: "1px solid var(--border-30)",
            padding: 10,
            overflowY: "auto",
            boxShadow: "0 8px 20px rgba(0,0,0,0.5)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <button type="button" onClick={() => step(-1)} style={NAV_BTN} aria-label="Previous month">‹</button>
            <span style={{ fontSize: 9.5, letterSpacing: "0.04em", color: "var(--t-80)" }}>
              {MONTHS[ym.m - 1]} {ym.y}
            </span>
            <button type="button" onClick={() => step(1)} style={NAV_BTN} aria-label="Next month">›</button>
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(7,1fr)",
              gap: 2,
              fontSize: 8.5,
              color: "var(--t-46)",
              marginBottom: 4,
              textAlign: "center",
            }}
          >
            {["S", "M", "T", "W", "T", "F", "S"].map((d, i) => (
              <span key={i}>{d}</span>
            ))}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: 2 }}>
            {cells.map((d, i) =>
              d === null ? (
                <span key={i} />
              ) : (
                <button
                  key={i}
                  type="button"
                  onClick={() => {
                    onChange(toIso(ym.y, ym.m, d));
                    setDraft(isoToDisplay(toIso(ym.y, ym.m, d)));
                    setInvalid(false);
                    setOpen(false);
                    inputRef.current?.focus({ preventScroll: true });
                  }}
                  aria-label={toIso(ym.y, ym.m, d)}
                  aria-pressed={d === selDay}
                  style={{
                    height: 18,
                    border: "none",
                    background: d === selDay ? "var(--accent)" : "transparent",
                    color: d === selDay ? "var(--bg)" : "var(--t-75)",
                    fontSize: 9,
                    cursor: "pointer",
                    borderRadius: 2,
                  }}
                >
                  {d}
                </button>
              ),
            )}
          </div>
        </div>
      )}
    </div>
  );
}

const NAV_BTN: React.CSSProperties = {
  background: "none",
  border: "none",
  color: "var(--t-70)",
  cursor: "pointer",
  fontSize: 11,
};
