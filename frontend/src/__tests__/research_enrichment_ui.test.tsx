import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderMarkup } from "./test_fixtures/render_markup";
import { NewsFeed } from "../features/news_feed/news_feed";
import { InstrumentPanel } from "../features/warrant_info/instrument_panel";
import { queryKeys } from "../data/query/query_keys";
import { createDefaultWatchlist, defaultWatchlistStorage } from "../domain/models/watchlist";
import { resetWatchlistMemoryForTests } from "../data/watchlist/use_watchlist";

const NEWS_KEY = queryKeys.research.news({ symbol: null, q: null, lang: "vi" });

function newsResponse(items: unknown[]) {
  return { items, count: items.length, has_more: false, next_before: null };
}

describe("NewsFeed — PostgreSQL-backed disclosure feed", () => {
  it("renders the dense TIME / SYMBOL / CATEGORY / HEADLINE table from seeded rows", () => {
    const html = renderMarkup(<NewsFeed />, [
      {
        queryKey: [...NEWS_KEY],
        data: newsResponse([
          {
            id: 1,
            title: "HPG: Board resolution on 2025 dividend",
            summary: "The board approved a cash dividend.",
            category: "Tin Tổ chức niêm yết",
            symbols: ["HPG"],
            published_at: "2026-08-20T02:30:00Z",
            url: "https://www.hsx.vn/x",
            source: "HSX",
          },
        ]),
      },
    ]);
    expect(html).toContain("TIME");
    expect(html).toContain("HEADLINE");
    expect(html).toContain("HPG: Board resolution on 2025 dividend");
    // causal restraint is stated in the feed, never "caused"
    expect(html).toContain("not causation");
    expect(html).not.toMatch(/caused (the |a )?price/i);
  });

  it("truthful empty state when nothing has been ingested — not an error", () => {
    const html = renderMarkup(<NewsFeed />, [{ queryKey: [...NEWS_KEY], data: newsResponse([]) }]);
    expect(html).toContain("No disclosures ingested yet");
    expect(html).not.toContain("Could not load");
  });

  it("a symbol filter narrows the subtitle and the query", () => {
    const html = renderMarkup(<NewsFeed filter="VPB" />, [
      {
        queryKey: [...queryKeys.research.news({ symbol: "VPB", q: null, lang: "vi" })],
        data: newsResponse([
          {
            id: 9,
            title: "VPB: capital raise",
            summary: null,
            category: null,
            symbols: ["VPB"],
            published_at: "2026-08-01T01:00:00Z",
            url: null,
            source: "HSX",
          },
        ]),
      },
    ]);
    expect(html).toContain("disclosures linked to VPB");
    expect(html).toContain("VPB: capital raise");
  });
});

describe("InstrumentPanel — CORP EVENTS wired to /api/research/corporate-actions", () => {
  beforeEach(() => {
    (globalThis as any).window = (globalThis as any).window || {};
    (globalThis as any).window.localStorage = {
      _s: {} as Record<string, string>,
      getItem(k: string) { return this._s[k] ?? null; },
      setItem(k: string, v: string) { this._s[k] = String(v); },
      removeItem(k: string) { delete this._s[k]; },
      clear() { this._s = {}; },
    };
    const fresh = createDefaultWatchlist();
    defaultWatchlistStorage.saveWatchlist(fresh);
    resetWatchlistMemoryForTests(fresh);
  });

  const stock = { symbol: "HPG", instrumentType: "STOCK" as const };

  it("renders real corporate-action rows on the QUANT tab", () => {
    const html = renderMarkup(
      <InstrumentPanel instrument={stock} marketSessionActive={false} onClose={vi.fn()} initialTab="quant" />,
      [
        {
          queryKey: [...queryKeys.research.corporateActions("HPG")],
          data: {
            symbol: "HPG",
            count: 1,
            items: [
              {
                id: 5,
                symbol: "HPG",
                action_type: "CASH_DIVIDEND",
                status: "CONFIRMED",
                ex_date: "2026-07-10",
                record_date: "2026-07-11",
                payment_date: "2026-07-25",
                disclosure_date: "2026-06-01",
                cash_amount_vnd: 500,
                ratio_pct: null,
                ratio_text: null,
                dividend_year: 2025,
                note: "Cash dividend",
                source: "VNDIRECT",
              },
            ],
          },
        },
      ],
    );
    expect(html).toContain("CORP EVENTS");
    expect(html).toContain("CASH DIV");
    expect(html).toContain("2026-07-10");
    expect(html).toContain("đ/sh");
    // the "not yet wired" placeholder is gone
    expect(html).not.toContain("not yet wired");
  });
});
