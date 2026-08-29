/**
 * Temporal data-state model - the frontend mirror of the backend
 * `app.market_data.temporal` vocabulary (Step 13C). The dashboard fallback resolver stamps
 * each value's origin so a UI cell can answer: what is the value, which session is it from,
 * when was it observed, is it live vs last-session vs unavailable.
 */

export type DataTemporalState =
  | "LIVE"
  | "LAST_SESSION"
  | "HISTORICAL"
  | "DERIVED"
  | "UNAVAILABLE";

export type DisplayState = "LIVE" | "LAST_SESSION" | "MIXED" | "UNAVAILABLE";

export interface FieldProvenance {
  state: DataTemporalState;
  source: string;
  asOf?: string | null;        // ISO8601 (VN)
  sessionDate?: string | null; // VN trading-session date
  stale?: boolean;
  note?: string | null;
}

export interface RowProvenance {
  quote: FieldProvenance;
  book: FieldProvenance;
  analytics?: FieldProvenance;
}

/** Short label for a display state (no styling opinion - the visual phase owns that). */
export function temporalLabel(state: DisplayState): string {
  switch (state) {
    case "LIVE":
      return "Live";
    case "LAST_SESSION":
      return "Last session";
    case "MIXED":
      return "Live / last session";
    case "UNAVAILABLE":
    default:
      return "Unavailable";
  }
}

/** "as of Fri 28 Aug" style helper from an ISO instant or a session date. */
export function asOfLabel(p?: FieldProvenance): string | null {
  const iso = p?.asOf || p?.sessionDate;
  if (!iso) return null;
  const d = new Date(iso.length <= 10 ? `${iso}T15:00:00+07:00` : iso);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "Asia/Ho_Chi_Minh",
  });
}
