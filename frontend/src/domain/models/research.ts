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
  title_en: string;
  title_en_exact: boolean;
  category_en: string;
  title: string;
  summary: string | null;
  category: string | null;
  source_language: string;
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

/** Unified research feed (Step 14B): HOSE disclosures + SSI/VNDirect company events. */
export type FeedContentType = "exchange_disclosure" | "company_event";

export interface ResearchFeedItem {
  id: string;
  symbol: string | null;
  published_at: string | null;
  /** English-first display fields (docs/design/LANGUAGE_POLICY.md). */
  title_en: string;
  /** false = a category/verb classification, not a rendered translation — see original. */
  title_en_exact: boolean;
  category_en: string;
  /** original Vietnamese, verbatim — provenance, shown in the expanded detail only. */
  title: string;
  summary: string | null;
  category: string | null;
  source_language: string;
  content_type: FeedContentType;
  source: string;
  source_url: string | null;
}

export interface ResearchFeedResponse {
  items: ResearchFeedItem[];
  count: number;
  has_more: boolean;
  next_before: string | null;
}

export interface ResearchFeedQuery {
  symbol?: string;
  source?: string;
  content_type?: FeedContentType;
  category?: string;
  event_class?: string;
  q?: string;
  lang?: "vi" | "en";
  limit?: number;
  before?: string;
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
  event_label: string;
  action_type: CorporateActionType | string;
  event_type?: string;
  event_class?: string;
  event_name?: string | null;
  source_language?: string;
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
