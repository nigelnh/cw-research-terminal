/**
 * Research-enrichment domain types (Step 14A).
 *
 * These map 1:1 onto the backend `/api/research/*` responses. Every field the backend
 * cannot populate arrives as `null` — the UI renders "—", never a fabricated value.
 * The browser never contacts an upstream source: all of this is PostgreSQL-backed data
 * assembled by controlled backend ingestion.
 */

export interface ResearchNewsItem {
  id: number;
  title: string;
  summary: string | null;
  category: string | null;
  symbols: string[];
  published_at: string | null;
  url: string | null;
  source: string;
}

export interface ResearchNewsResponse {
  items: ResearchNewsItem[];
  count: number;
  has_more: boolean;
  next_before: string | null;
}

export type CorporateActionType =
  | "CASH_DIVIDEND"
  | "STOCK_DIVIDEND"
  | "BONUS_ISSUE"
  | "RIGHTS_ISSUE"
  | "AGM"
  | "EGM"
  | "LISTING"
  | "DELISTING"
  | "OTHER";

export interface CorporateActionItem {
  id: number;
  symbol: string;
  action_type: CorporateActionType | string;
  status: string;
  ex_date: string | null;
  record_date: string | null;
  payment_date: string | null;
  disclosure_date: string | null;
  cash_amount_vnd: number | null;
  ratio_pct: number | null;
  ratio_text: string | null;
  dividend_year: number | null;
  note: string | null;
  source: string;
}

export interface CorporateActionsResponse {
  symbol: string;
  items: CorporateActionItem[];
  count: number;
}

export interface CompanyProfileResponse {
  symbol: string;
  exchange: string | null;
  vn_name: string | null;
  en_name: string | null;
  industry: string | null;
  found_date: string | null;
  website: string | null;
  listed_shares: number | null;
  outstanding_shares: number | null;
  news_count: number;
  source: string | null;
}
