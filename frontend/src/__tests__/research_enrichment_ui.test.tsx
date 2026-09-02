import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderMarkup } from "./test_fixtures/render_markup";
import { NewsFeed } from "../features/news_feed/news_feed";
import { InstrumentPanel } from "../features/warrant_info/instrument_panel";
import { queryKeys } from "../data/query/query_keys";
import {
  createDefaultWatchlist,
  defaultWatchlistStorage,
} from "../domain/models/watchlist";
import { resetWatchlistMemoryForTests } from "../data/watchlist/use_watchlist";

const FEED_KEY = queryKeys.research.feed({
  symbol: null,
  source: null,
  contentType: null,
  eventClass: null,
  q: null,
  lang: "vi",
});

/** useInfiniteQuery cache shape. English-first fields default from the raw `title`. */
function feedPages(items: any[], next_before: string | null = null) {
  const withEn = items.map((it) => ({
    title_en: it.title,
    title_en_exact: true,
    category_en: it.category ?? "HOSE disclosure",
    source_language: "vi",
    ...it,
  }));
  return {
    pages: [
      {
        items: withEn,
        count: withEn.length,
        has_more: next_before != null,
        next_before,
      },
    ],
    pageParams: [undefined],
  };
}

describe("NewsFeed — unified research feed", () => {
  it("renders the dense DATE / SYMBOL / TYPE / HEADLINE / SOURCE table from seeded rows", () => {
    const html = renderMarkup(<NewsFeed />, [
      {
        queryKey: [...FEED_KEY],
        data: feedPages([
          {
            id: "news_1",
            title: "HPG: Board resolution on 2025 dividend",
            summary: "The board approved a cash dividend.",
            category: "Tin Tổ chức niêm yết",
            symbol: "HPG",
            published_at: "2026-08-20T02:30:00Z",
            source_url: "https://www.hsx.vn/x",
            source: "HOSE",
            content_type: "exchange_disclosure",
          },
          {
            id: "event_5",
            title: "HPG · FINANCIAL_STATEMENT",
            summary: "HPG - BCTC Quý 2/2026",
            category: "FINANCIAL",
            symbol: "HPG",
            published_at: "2026-07-30",
            source_url: null,
            source: "SSI",
            content_type: "company_event",
          },
        ]),
      },
    ]);
    expect(html).toContain("Date");
    expect(html).toContain("Headline");
    expect(html).toContain(">Source<");
    expect(html).toContain("HPG: Board resolution on 2025 dividend");
    expect(html).toContain("Disclosure");
    expect(html).toContain("Event");
    // Vietnamese category label is not in the collapsed table
    expect(html).not.toContain("Tin Tổ chức niêm yết");
    // causal restraint is stated, never "caused"
    expect(html).toContain("Official disclosures and company events");
    expect(html).not.toMatch(/caused (the |a )?price/i);
  });

  it("truthful empty state when nothing has been ingested — not an error", () => {
    const html = renderMarkup(<NewsFeed />, [
      { queryKey: [...FEED_KEY], data: feedPages([]) },
    ]);
    expect(html).toContain("No matching news or events");
    expect(html).not.toContain("Could not load");
  });

  it("a typed symbol stays a text query until an explicit symbol filter is chosen", () => {
    const key = queryKeys.research.feed({
      symbol: null,
      source: null,
      contentType: null,
      eventClass: null,
      q: "VPB",
      lang: "vi",
    });
    const html = renderMarkup(<NewsFeed filter="VPB" />, [
      {
        queryKey: [...key],
        data: feedPages([
          {
            id: "news_9",
            title: "VPB: capital raise",
            summary: null,
            category: null,
            symbol: "VPB",
            published_at: "2026-08-01T01:00:00Z",
            source_url: null,
            source: "HOSE",
            content_type: "exchange_disclosure",
          },
        ]),
      },
    ]);
    expect(html).toContain('value="VPB"');
    expect(html).toContain("VPB: capital raise");
  });

  it("empty results expose a clear-filters recovery action", () => {
    const html = renderMarkup(<NewsFeed />, [
      { queryKey: [...FEED_KEY], data: feedPages([]) },
    ]);
    expect(html).toContain("Clear filters");
    expect(html).not.toContain("not yet wired");
  });

  it("shows a LOAD OLDER control when more pages exist (never the whole corpus at once)", () => {
    const html = renderMarkup(<NewsFeed />, [
      {
        queryKey: [...FEED_KEY],
        data: feedPages(
          [
            {
              id: "news_1",
              title: "x",
              summary: null,
              category: null,
              symbol: "HPG",
              published_at: "2026-08-01",
              source_url: null,
              source: "HOSE",
              content_type: "exchange_disclosure",
            },
          ],
          "2026-07-31T00:00:00Z",
        ),
      },
    ]);
    expect(html).toContain("Load older");
  });
});

describe("InstrumentPanel — CORP EVENTS wired to /api/research/corporate-actions", () => {
  beforeEach(() => {
    (globalThis as any).window = (globalThis as any).window || {};
    (globalThis as any).window.localStorage = {
      _s: {} as Record<string, string>,
      getItem(k: string) {
        return this._s[k] ?? null;
      },
      setItem(k: string, v: string) {
        this._s[k] = String(v);
      },
      removeItem(k: string) {
        delete this._s[k];
      },
      clear() {
        this._s = {};
      },
    };
    const fresh = createDefaultWatchlist();
    defaultWatchlistStorage.saveWatchlist(fresh);
    resetWatchlistMemoryForTests(fresh);
  });

  const stock = { symbol: "HPG", instrumentType: "STOCK" as const };

  it("renders real corporate-action rows on the QUANT tab", () => {
    const html = renderMarkup(
      <InstrumentPanel
        instrument={stock}
        marketSessionActive={false}
        onClose={vi.fn()}
        initialTab="quant"
      />,
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
    expect(html).toContain("Company events");
    expect(html).toContain("cash dividend");
    expect(html).toContain("2026-07-10");
    expect(html).toContain("VND/share");
    // no Vietnamese unit label
    expect(html).not.toContain("đ/sh");
    // the "not yet wired" placeholder is gone
    expect(html).not.toContain("not yet wired");
  });
});
