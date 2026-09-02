# UX/UI refinement handover

Branch: `codex/ux-ui-refinement`, based on `c6367a0`.
Worktree: `/private/tmp/cw-terminal-ux`.
Claude's checkout remains `/Users/nhannguyen/Developer/cw-research-terminal` on `feat/ui-polish-pass`.

## Local review

Open **http://localhost:3001/ux-preview.html**. The top bar identifies fixed test data and switches between Live, Last session, Empty data and API error. This isolated fixture service never imports the production app, credentials, a database or FiinQuant. AI responses and the sign-in test are local fixtures; the sign-in dialog itself uses the normal UI, without sending email.

The fixture entry is excluded from the production build. It is for reviewing interactions and layout, not current prices or validating an investment decision. Real News repository/API behavior is tested separately against temporary PostgreSQL.

To restart from this worktree, use separate terminals:

```sh
/Users/nhannguyen/Developer/cw-research-terminal/backend/.venv/bin/python tools/ux_preview.py
```

```sh
cd frontend
VITE_MARKET_DATA_REST_URL=http://127.0.0.1:8502 VITE_MARKET_DATA_WS_URL=ws://127.0.0.1:8502/ws/market npm run dev -- --host 127.0.0.1 --port 3001 --strictPort
```

The normal entry remains `frontend/index.html`. Actual provider testing requires the existing backend environment and the usual single FiinQuant owner; do not start another provider session alongside Claude's running backend. Production deployment is a separate review step. Deploy the additive backend News API before the frontend that consumes it.

## Implemented

- Explicit index points versus VND in snapshots, patches, fallback and charts; signed change formatting. Missing prices/analytics remain unavailable, including clearing explicitly null analytics patches.
- Current calendar DTE in ICT for Watchlist, Research and Overview; last-trading date remains separate. Model DTE and analytics calculation timestamp are preserved. Cached quotes cannot create a candle at the current browser time.
- Actual quote/analytics timestamps, date-only session labels without invented clock times, independent market-session and backend-connection indications, loading/error/empty recovery.
- Active-warrant lifecycle, verification and watchlist membership shown separately; conflicting metadata withholds analytics.
- Header symbol suggestions with `/`, Enter, arrow keys and Escape. Independent Watchlist/Research/News text filters.
- DB-side multi-symbol/date/English-classification/original-language News filtering, full-corpus symbol facets and `(timestamp, ID)` cursor pagination. Legacy fields and `before` remain accepted. No migration, translation service or provider added.
- Inter body typography, IBM Plex Mono prices/tickers, Rousseau Deco brand/navigation; shared controls, click/keyboard popovers, native calendars, focus, tooltips and empty/error states.
- One Watchlist schema, Basic/Full columns, Market/Contract/Volatility grouping, keyboard sort/selection, grouped pins, Hide/Remove and working Undo. Filter options remain based on unfiltered data.
- Explicit starting guidance, Browse research and Open assistant actions; no automatic instrument selection or new product seed data.
- Resizable/persisted/expandable detail panel. Overview prioritises the chart and contract; unsupported book/prints/fundamentals have compact availability notes.
- Daily history with 1M/3M/6M/1Y, default 6M, Warrant/Underlying/Both/Relative, REF/EMA controls. Underlying history loads only for comparison and shares the existing cache/pipeline. Price overlays are disabled for relative returns.
- Quant grouped into Volatility/Valuation/Greeks, units/tooltips and expandable model provenance. Stock detail has an Events tab.
- News All market/Watchlist/Selected scopes; a ticker click opens detail without changing scope. Separate filter-by-symbol action, source-specific date labels, Upcoming, Classified headline and Vietnamese originals/official links.
- Orbit and existing random greetings retained; context chip, Expand/Dock, wider reading surface, Copy/Stop/Retry. Stop persists partial output; Retry reuses the failed question/context without another user turn, guarded against late stream updates.
- Laptop layout at 1024px and above; single-column detail and wide AI overlay below. Watchlist/registry scroll inside their own region with sticky symbols. Mobile News displays readable headline cards. Sign-in has Close, Email label, focus restoration/trap and consistent sending feedback.

## Verification

- Frontend: **243 tests passed** across 31 files; TypeScript and production build passed.
- Backend: **518 passed, 20 skipped** across enrichment, resolver/EOD alignment, registry, session and quant suites. The skips are deliberately excluded degenerate/unsolvable quant vectors, not missing provider access.
- DB tests cover English `dividend`, literal Vietnamese, multi-symbol/empty selection, inclusive ICT date ranges, items beyond the first page, equal-timestamp pagination, corpus facets, invalid cursor/date/symbol input and additive API fields.
- Interaction tests cover Basic/Full, row keyboard selection, parent/CW pin hierarchy, sort, Hide/Remove/Undo, filter/date/Escape/outside click, header jump, News ticker scope, sign-in focus/feedback and AI Stop/Retry races.
- Browser review: 1440×900 Watchlist/chart/comparison and AI expand/dock; 1280×800 Quant; 1024×768 News/filter keyboard/calendar; 390×844 News, scrolling tables, single-column detail, AI Stop/Retry/Copy and sign-in. Keyboard resizing persists after reload. Chart sizing stays bounded after resizing/docking; Orbit clears the docked composer and restores focus after minimising. Long registry/headlines, live/last-session, empty and error fixtures reviewed. No console errors in the final normal-flow browser check. [Review screenshots](ux-review/README.md).
- Existing Vite bundle-size warning remains (main JS approximately 894 kB before gzip); it does not fail the build. No production deployment or external AI/provider request was performed.

## Suggested manual pass

1. Switch Basic/Full; sort and pin HPG/VPB, then a child CW. Hide, Remove and Undo each.
2. Use `/` to jump to CHPG2602. Resize/expand, change ranges and compare with HPG. Open Quant and provenance.
3. Browse Research and inspect CTCB2601's conflicting metadata. Quant values should be withheld.
4. Search `dividend` in News. Try scopes, several symbols, date bounds, Load older and a ticker click.
5. Open Orbit, send a fixture question, Stop, Retry, Copy, Expand and Dock. Test a narrow viewport and sign-in Close/Escape.
