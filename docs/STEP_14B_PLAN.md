# Step 14B — Historical News/Event Corpus + Persistent AI UX — Implementation Plan

_Audit + live-source testing done 2026-08-31. This is the implementation-discipline plan;
the final report records outcomes._

## Part 0 — Step 14A post-merge verification (DONE)

- PR #5 + #6 merged to `main` (`05b9224`). Railway deployment `3840f947` SUCCESS.
- Alembic `0004` at `head`. `/api/research/*` live.
- **Category backfill run** — `cli news --days 30 --lang vi --lang en` → 4000/4000 rows now
  carry a `category` (bounded detail fetch per `(lang, catId)` from PR #6). Dominant
  category "Tin Tổ chức niêm yết" (issuer news). Minor: some EN rows kept the VN category
  label — cosmetic, noted.
- **AI routing verified in production** — `POST /api/ai/chat` with "what corporate actions
  has VPB had?" now returns real ingested events (2024–2026 dividends, AGMs, listings) with
  the causal-restraint note. `get_corporate_actions` is reachable.

## Part 1 — Source viability (live-tested 2026-08-31)

### SSI structured company events — VIABLE (distinct endpoint)

`GET https://iboard-api.ssi.com.vn/statistics/company/ssmi/corporate-actions`
`?pageSize=&page=&language=en|vi&symbol=&fromDate=DD/MM/YYYY&toDate=DD/MM/YYYY`

- **200 OK** from a plain server context with the honest UA. This is a **different host**
  (`iboard-api` vs the `iboard-query` host that 403'd in 14A) — the rejection does not
  generalize. Re-tested independently.
- **Date-range ceiling ≈ 1 year.** A 24-month range returns `code:SUCCESS, data:null,
  totalPage:0` (silent empty). ≤12-month ranges return data. → crawler MUST chunk by
  calendar year.
- Volume: HPG ~26 events/year. 13 underlyings × 2y ≈ ~680 events total. `pageSize=1000`
  ⇒ `totalPage` is 1 in practice — pagination is trivial but implemented for safety.
- Fields: `symbol, eventName (VI label), eventListCode, eventTitle, eventDescription (HTML),
  exchange, exrightDate, recordDate, issueDate, publicDate, sortExrightDate, value, ratio,
  eventCode (usually null)`. Dates `DD/MM/YYYY`.
- `eventListCode` seen: `KQQY` (quarterly financials), `KQCT`, `DDRP`/`DDALL` (insider /
  related-party transactions), `AGME` (AGM), `ISS`/`AIS` (share issuance), `OTHE`.
  **These are broad COMPANY EVENTS — most are not price-adjustment corporate actions.**
  `AGME` and `ISS` carry an `exrightDate` but an AGM is not a price adjustment.

### HOSE official news — VIABLE, large

`GET https://api.hsx.vn/n/api/v1/{langId}/news?pageSize=&startDate=YYYY-MM-DD&endDate=&pageIndex=`

- ~2,400–3,500 news/month (VI); EN similar. 24 months VI ≈ **60,000 rows**.
- `pageSize` accepts up to **500** (7 pages/month) — use 200 as a safe default.
- `aliasCate=tin-tuc` does not change results — omit it.
- A calendar month at pageSize=200 ≈ 18 pages; still under a safety cap. A month at
  pageSize=50 = ~70 pages ⇒ would truncate at the old cap → **adaptive split** month→week
  when `totalPages > cap`.

### Underlying universe (registry-derived)

`active_warrants.json` (all 533 discovered CWs) → **13 distinct underlyings**:
`FPT HPG MBB MSN MWG STB TCB VHM VIC VJC VNM VPB VRE`. This is the SSI backfill universe
(not the 5-symbol watchlist, not hardcoded).

## Part 2 — Schema decision

**Chosen: rename `corporate_actions` → `company_events` and generalise it.** (`0005`)

Rationale: 14A already stored AGM/EGM/LISTING in `corporate_actions` — the name was already
wrong for most rows. SSI adds financial statements and insider transactions, which are
unambiguously *not* corporate actions in the price-adjustment sense. A single typed
company-event model is the honest home; a parallel `company_events` table beside
`corporate_actions` would be the "duplicate domain model" the brief warns against.

Migration `0005` (Postgres `ALTER TABLE RENAME` — instant, transactional, reversible;
no data copy, no drop):
- `corporate_actions` → `company_events`
- add `event_class` (`DIVIDEND | RIGHTS | MEETING | LISTING | FINANCIAL | OWNERSHIP | OTHER`),
  backfilled from the existing `action_type`
- rename `action_type` → `event_type`; widen vocabulary
  (`+FINANCIAL_STATEMENT, INSIDER_TRANSACTION, ADDITIONAL_LISTING`)
- add `event_name` (source's own label), `public_date`, `value_text`
- relax the two CHECK constraints to the new vocabularies
- `raw` JSONB already present — SSI payloads preserved verbatim (no headers/secrets)
- indexes: keep `(symbol, ex_date)`; add `(symbol, event_class)`, `(source, source_id)` unique kept

`corporate_actions` semantics preserved for consumers via
`repository.list_corporate_actions()` → filters `event_class in (DIVIDEND, RIGHTS, MEETING,
LISTING)`. New `repository.list_company_events()` returns the full stream.

**`external_news`** — extended in place (`0005`): `source` widens to include `HOSE`
(the historical-crawl rows; 14A's HSX rows stay `HSX` — same upstream, kept distinct only
if evidence shows divergence, else normalised to `HOSE` going forward). Add `content_type`
(`exchange_disclosure`), `coverage`-tracking handled in `source_fetch_log`, not the row.
Unique key stays `(source, source_id, lang)` — HOSE `id` is the `source_id`.

**SSI vs HOSE kept semantically distinct** — no cross-source dedup. SSI = structured
company event (`company_events`, `source=SSI`); HOSE = exchange disclosure artifact
(`external_news`, `source=HOSE`). The unified feed surfaces both; clustering is a later
concern.

**SSI deterministic identity** — `eventCode` is usually null. Key =
`sha1(symbol | eventListCode | eventTitle | publicDate | issueDate | exrightDate | recordDate)`
truncated; source `eventCode` preserved separately in `raw` and a nullable `source_event_code`.

## Part 3 — Crawlers

New `app/enrichment/`:
- `ssi_source.py` — `SsiCompanyEventsSource.iter_events(symbol, *, from_date, to_date, lang)`
  — calendar-year chunking, `pageSize=1000`, page loop, hard cap.
- `normalize.py` += `classify_ssi_event()`, `normalize_ssi_event()`.
- `hose_crawler.py` — month-chunk generator with **adaptive split**: a chunk whose
  `totalPages > SETTINGS cap` recurses month→half-month→week until each sub-window is fully
  retrievable. Emits a per-window `complete: bool`.
- `cli.py` += `backfill-events` (SSI, 24-month, 13 underlyings, year chunks),
  `backfill-news` (HOSE, 24-month, month chunks + adaptive split), `enrich-incremental`
  (rolling overlap window — SSI 45d, HOSE 10d), `coverage` (report completeness).
- `source_fetch_log` extended: `window_start`, `window_end`, `page`, `inserted`, `updated`,
  `complete` — one row per (source, window, page) so coverage is queryable.

All: idempotent upsert, bounded backoff, low concurrency, restart-safe (resume from the
last logged complete window), zero FiinQuant imports.

## Part 4 — Unified feed API

Extend `/api/research` (no new `/api/news`):
- `GET /api/research/feed` — unified cursor-paginated feed over `external_news` +
  `company_events`. Filters: `symbol, source, content_type, category, event_class, from, to,
  q`. Cursor on `(published_at, id)`. Response rows:
  `{id, symbol, published_at, title, summary, category, content_type, source, source_url}`.
- `GET /api/research/events/{symbol}` — company events for one symbol (replaces the
  corporate-actions-only endpoint; the old path kept as an alias filtered to the CA subset).
- Existing `/news`, `/corporate-actions/{symbol}`, `/company/{symbol}` kept working.
- Indexes for the feed: `external_news (published_at desc, id)`,
  `company_events (published_at-ish desc)` — add a `sort_date` generated/coalesced column
  or order by `coalesce(ex_date, public_date, disclosure_date)`.

## Part 5 — AI

- `get_corporate_actions` — unchanged signature; now reads `company_events` filtered to the
  price-sensitive + meeting subset (backwards compatible).
- `get_company_events(symbol, classes?, limit?)` — new bounded tool over the full stream.
  Router intent: financials / insider / "events" keywords → `get_company_events`;
  dividend / ex-date / meeting keywords → `get_corporate_actions` (unchanged).
- Both PostgreSQL-only, clamped, `causal_note` + `provenance` preserved.
- System prompt: add `get_company_events` to the RESEARCH_ENRICHMENT block; reinforce that
  a financial-statement disclosure or insider trade is an *event*, not a corporate action,
  and never a cause.

## Part 6 — Frontend: News typography

Audit `research_universe.tsx` vs `news_feed.tsx` computed type. Align News to the same
Grid Terminal scale/classes for peer elements: section title (`heading` 14/700), context
line (10.5 italic), column headers (9.5/0.06em), row body (`mono` 11.5), symbol
(`--accent`), category (`--t-55/60`), headline (`--t-85`), expanded summary (11/1.55).
Reuse shared classes; no arbitrary px bumps. Visual QA News vs Research at 1440/1680.

## Part 7 — Frontend: draggable AI anchor + fixed panel

- **Icon** — from `lucide-react` (already a dep): `Sparkles` / `Orbit` / `Asterisk` —
  pick after inspecting; no robot, no new dep. A quiet 16px stroke mark.
- **`AiAnchor`** — fixed-position button, default bottom-right (safe inset), pointer-events
  drag with a 4px move threshold to distinguish drag from click, viewport clamp on drag +
  on `resize`, position persisted in `localStorage` under the project's versioned prefs key.
  Keyboard: focusable, Enter/Space toggles, `aria-expanded`.
- **`AiConversationPanel`** — fixed `width: min(380px, calc(100vw - 32px))`,
  `height: min(460px, calc(100vh - 120px))`, internal `overflow-y:auto` on the message
  list. Placement flips based on which viewport quadrant the anchor sits in
  (anchor bottom-right → panel opens up-left). Never overflows; never resizes the terminal;
  streaming text scrolls inside. Narrow viewports (<640px) → bottom-sheet variant, same state.
- States: `collapsed | open | streaming | error | dragging`. Minimise keeps the conversation.
- The bottom REPL **input** stays docked (best place to type); the panel owns the
  **response/conversation** surface, visually tied to the anchor with a restrained connector.
- `ai_repl_bar.tsx` refactor: split input (docked) from output (panel). `useAiChat`
  unchanged.

## Part 8 — Scheduling

Decision after Part 3: Railway Free Trial has **no cron primitive** without a paid plan /
a new always-on service. GitHub Actions `schedule:` is zero-cost, secure (repo secret for a
scoped ingestion token or the DB URL), and does not touch the FiinQuant process. Proposed:
a scheduled workflow that runs `python -m app.enrichment.cli enrich-incremental` against the
production DB on a cadence (SSI daily post-close ~10:00 ICT; HOSE every 6h). **No public
"run ingestion" endpoint.** If the user prefers not to put the prod DB URL in a GH secret,
the CLI stays manual and this is the one approval gate.

## Part 9 — Tests, backfill, deploy

- Backend: SSI normalize (null eventCode, deterministic key, classification, unknown type,
  raw preserved), year-chunk math frozen at 2026-08-31 (partial 2024 / full 2025 / YTD
  2026), HOSE monthly pagination + adaptive split + coverage-complete flag, symbol
  resolution (prefix + registry validation + CW-style + unresolved), idempotent rerun,
  unified feed (SSI-only / HOSE-only / both / filters / pagination / recent-first / no
  cross-dedup). Frontend: News typography token reuse; AI anchor (default pos, click vs
  drag, clamp, persistence, resize recovery, fixed panel dims, long answer scroll, no
  layout resize, keyboard toggle, existing chat path).
- Full gates: `pytest`, `pyright app`, repo hygiene; `tsc`, `vitest`, `vite build`.
- Production: `0005` on deploy; `backfill-events` + `backfill-news` via `railway ssh`;
  incremental run ×2 (idempotency proof); smoke.

## Gates that need the user

1. **PR merge** (permissions block `gh pr merge`).
2. **Scheduling** — only if GH Actions with a prod-DB secret is not acceptable.
