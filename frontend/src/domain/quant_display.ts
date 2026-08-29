/**
 * Canonical display conventions for CW quant surfaces.
 *
 * ONE definition each for spread, spread %, and the moneyness label - consumed identically
 * by the UI and by the AI research-context envelope. Nothing here recomputes a value the
 * backend already owns: implied vol, greeks, HV, theoretical price, the numeric moneyness
 * ratio and the ITM/ATM/OTM category all come from the backend quant engine unchanged.
 * These helpers only cover the two purely quote-derived values (spread, spread %) and
 * formatting.
 */

export interface SpreadResult {
  /** ask - bid, in raw VND. null unless both sides are present and the quote is not crossed. */
  abs: number | null;
  /** 100 * (ask - bid) / mid, mid = (bid + ask) / 2. null on the same conditions. */
  pct: number | null;
}

/**
 * Bid/ask spread and spread-%.
 *
 * Convention (the single source of truth):
 *   spread      = ask - bid
 *   mid         = (bid + ask) / 2
 *   spreadPct   = 100 * spread / mid
 *
 * Returns nulls (UI renders "—") unless: bid > 0, ask > 0, ask >= bid, mid > 0.
 * A crossed or one-sided quote is never coerced into a number.
 */
export function computeSpread(
  bid: number | null | undefined,
  ask: number | null | undefined,
): SpreadResult {
  if (
    typeof bid !== "number" ||
    typeof ask !== "number" ||
    !Number.isFinite(bid) ||
    !Number.isFinite(ask) ||
    bid <= 0 ||
    ask <= 0 ||
    ask < bid
  ) {
    return { abs: null, pct: null };
  }
  const mid = (bid + ask) / 2;
  if (mid <= 0) return { abs: null, pct: null };
  const abs = ask - bid;
  return { abs, pct: (abs / mid) * 100 };
}

/** A decimal fraction (0.325) -> "32.5%". null/NaN -> em-dash. */
export function formatPct(value: number | null | undefined, dp = 1): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(dp)}%`;
}

/** Raw VND price -> grouped integer string with a ₫ suffix. */
export function formatVnd(value: number | null | undefined, dp = 0): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp })} ₫`;
}

/** Per-greek display precision (see docs/domain/quant_display_conventions.md). */
export function formatGreek(
  name: "delta" | "gamma" | "theta" | "vega" | "rho",
  value: number | null | undefined,
): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  switch (name) {
    case "delta":
      return value.toFixed(4);
    case "gamma":
      return value.toExponential(2); // tiny per-VND number; exponent form is honest
    case "theta":
    case "vega":
    case "rho":
      return `${value.toFixed(2)} ₫`;
  }
}

/**
 * Calendar days from *today in Vietnam* to `dateStr` (YYYY-MM-DD), floored at 0 - matches
 * the backend `days_to_expiry` = `(maturity.date() - vn_now.date()).days`. Pure date math,
 * no wall-clock time, no host-timezone drift.
 */
export function daysUntil(dateStr: string | null | undefined, now: Date = new Date()): number | null {
  if (!dateStr || !/^\d{4}-\d{2}-\d{2}/.test(dateStr)) return null;
  const [ty, tm, td] = dateStr.slice(0, 10).split("-").map(Number);
  const vnToday = now.toLocaleDateString("en-CA", { timeZone: "Asia/Ho_Chi_Minh" }); // "YYYY-MM-DD"
  const [ny, nm, nd] = vnToday.split("-").map(Number);
  const diff = (Date.UTC(ty, tm - 1, td) - Date.UTC(ny, nm - 1, nd)) / 86_400_000;
  return Math.max(0, Math.round(diff));
}

const CONTRACT_STATE_LABEL: Record<string, string> = {
  ACTIVE: "Active",
  NEAR_EXPIRY: "Near expiry",
  LAST_TRADING_DAY: "Last trading day",
  PENDING_MATURITY: "Trading closed · awaiting settlement",
  EXPIRED: "Expired",
  UNKNOWN: "—",
};

export function contractStateLabel(state: string | null | undefined): string {
  if (!state) return "—";
  return CONTRACT_STATE_LABEL[state] ?? state;
}
