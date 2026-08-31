# Step 14B — final report

**Historical research corpus · unified feed · persistent AI UX · post-incident recovery ·
English-first language layer.**

Date closed: 2026-08-31 · Backend: Railway (`backend`) · DB: Railway PostgreSQL
`Postgres-lfpZ` · Frontend: Vercel · PRs merged: #7, #8, #9, #10, #11.

---

## 0. What shipped

| Area | Result |
|---|---|
| Corpus | 24-month HOSE disclosure corpus (81,322 VI rows, 2024-09-04 → 2026-08-28) + 1,150 structured company events (SSI 717 · VNDirect 433) |
| Schema | Alembic **0006** (`0004→0005→0006`); `corporate_actions`→`company_events`; `external_news.raw` dropped |
| API | `/api/research/feed` (unified, cursor-paginated), `/news`, `/events/{sym}`, `/corporate-actions/{sym}`, `/company/{sym}` |
| AI | `get_news`, `get_company_events`, `get_corporate_actions` in the proactive tool path; causal-restraint guardrail; English-first response policy |
| Frontend | NEWS tab (unified feed + LOAD OLDER, English-first), draggable Orbit anchor + fixed conversation panel, "×" row dismiss |
| Incident | 2026-08-31 volume-fill → full local recovery → cutover to a fresh Railway DB → hardening guard |
| Language | English-first product on a Vietnamese-canonical source (this report §1–§6) |

Full incident record: `scratchpad/POSTGRES_RECOVERY_SNAPSHOT.md` (local, gitignored).
Language design + audit: `docs/design/LANGUAGE_POLICY.md`.

---

## 1. Canonical source language

**Vietnamese is the canonical HOSE ingestion feed.** This is a data-ownership decision,
independent of the product's display language.

- HOSE exposes `langId=1` (vi) and `langId=2` (en). The **vi** feed has the full, useful
  coverage: 81,322 rows over a complete 24 months, 94.7% symbol-linked.
- The **en** feed is **not** a localization of vi — it uses a **disjoint `source_id`
  space** (`shared source_id count = 0`), covered only ~21 of 24 months at the time of the
  incident, and is dominated by ETF-NAV / "Foreign Investors Shareholding Data" notices
  with low covered-warrant research value.
- SSI and VNDirect company events are Vietnamese at source too; their `event_class` /
  `event_type` are normalized to English enums at ingestion.

**Decision:** vi is canonical and permanent. **EN market-wide ingestion is disabled.**
`enrich-incremental` and `bootstrap` read `ENRICHMENT_INCREMENTAL_HOSE_LANGS` (default
`"vi"`); a deliberate, scoped EN pull is still possible via an explicit
`backfill-news --lang en`, but is not part of steady-state operation.

The unattended crawler was found (during post-recovery verification) to have re-crawled EN
market-wide because `_cmd_enrich_incremental` hard-coded `lang=["vi","en"]` — fixed in
PR #9, cleanup in §7.

---

## 2. Product presentation language

**CW Research Terminal is English-first on every user-facing surface.**

| Surface | Status |
|---|---|
| Navigation, tabs, table headers, filter chips, buttons, empty/error states, instrument panel, AI REPL chrome | **English** — already, and audited |
| News `HEADLINE` | **English** — `title_en` (§4) |
| News `TYPE` / category | **English** — `EVENT` / `DISCLOSURE`; `category_en` in the expanded detail |
| Company-event labels (feed + instrument-panel CORP EVENTS) | **English** — `event_label` from the enums, e.g. *"Cash dividend"*, *"Insider transaction"*, *"New listing"* |
| Original Vietnamese title / summary / category | **preserved**, shown only in the expanded row under an explicit *"Original (Vietnamese)"* label |

Vietnamese now appears in the product **only** as explicitly-marked original-source
content, or when a user chooses Vietnamese in the AI conversation (§3).

Implementation: `backend/app/enrichment/english.py` — pure, deterministic, no I/O, no
migration. Applied at read time in the API layer, so it works on every existing row
immediately.

---

## 3. AI response-language policy

**Default English. Vietnamese only when the user's own latest substantive message is
Vietnamese.** Never inferred from thread history, retrieved source-record language, or the
selected symbol.

Mechanism (defence in depth, because the production model `minimax/minimax-m3:free` is a
weak instruction-follower):

1. `detect_reply_language()` — deterministic: the reply language is Vietnamese iff the
   user's latest message contains Vietnamese diacritics, else English.
2. `RESPONSE LANGUAGE FOR THIS REPLY: <lang>` is prepended to the **top** of the system
   prompt with an explicit "regardless of earlier turns or retrieved records" clause.
3. `[Respond in English.]` / `[Trả lời bằng tiếng Việt.]` is appended to the final user
   turn (the position a weak model weights most).
4. The `BASE_SYSTEM_INSTRUCTIONS` language section states the English-first rule and the
   "translate VI source into English, keep provenance, invent nothing, keep causal
   restraint" requirement.

**Production verification (fresh threads, no explicit language instruction):**

| Scenario | Result |
|---|---|
| English question | English answer ✓ |
| Vietnamese question | Vietnamese answer ✓ |
| VI thread → un-flagged English follow-up | English answer ✓ (regressed before step 3 was added; fixed) |
| EN thread → un-flagged Vietnamese follow-up | Vietnamese answer ✓ |
| English question about HOSE disclosures | English answer, VI titles translated inline, dates + "HOSE filings" provenance kept, no causal attribution ✓ |

The AI `get_news` / `get_company_events` / `get_corporate_actions` payloads now carry both
the English fields (`title_en`, `label`, `category_en`) and `*_original` for provenance.

---

## 4. English News normalization — coverage

`headline_en(title)` classifies the (highly templated) HOSE disclosure title into a
canonical English disclosure-type phrase and carries the period token
(`Q3/2025`, `H1 2026`, `2025`, `27/08/2026`). Measured over the full 81,322-row corpus:

| bucket | rows | share |
|---|---|---|
| **specific disclosure-type rule** (`title_en_exact = true`) | 74,080 | **91.1%** |
| leading-verb classification (`exact = false`) — *"Notice — X"*, *"Report — X"* | 5,920 | 7.3% |
| category classification (`exact = false`) — *"Listed-issuer disclosure — X"* | 1,322 | 1.6% |

`category_en` — a hand-written dictionary over **every** observed HOSE `catName`: **100%
deterministic coverage**; an unmapped value degrades to `"HOSE disclosure"`.

`event_label_en` / `event_class_label_en` — from the already-English `event_class` /
`event_type` enums: **100%**, never the raw Vietnamese `event_name`.

Rule engine: ~110 ordered keyword rules (`app/enrichment/english.py`), most-specific
first, plus 8 weak leading-verb rules. 13 unit tests in
`tests/enrichment/test_english.py`.

---

## 5. Exact-title vs fallback-title behaviour

`title_en_exact` is the confidence/provenance flag exposed on every feed and news item:

- **`true`** — a disclosure-type rule matched. The English is a canonical rendering of the
  *kind* of disclosure (e.g. *"Corporate governance report, H1 2026 — HPG"*,
  *"ETF net asset value (NAV) notice, 27/08/2026 — FUEKIV30"*). It is **not** claimed to be
  a literal translation of the filing's own wording — the verbatim Vietnamese title is
  always attached.
- **`false`** — no rule matched. The headline is an honest classification only
  (*"Notice — VFG"*, *"Listed-issuer disclosure — XYZ"*), rendered in the News table with a
  subtle `~` marker and, in the expanded row, the note *"headline classified from category,
  not a translation"*.

We never fabricate a precise translation of an out-of-pattern title.

---

## 6. Original-source preservation

Nothing Vietnamese is destroyed or overwritten.

- `external_news.title`, `.summary_html`, `.category` — **unchanged in the database**; the
  English fields are computed at read time.
- `company_events.event_name`, `.note` — **kept**; `event_label` is additive.
- `company_events.raw` (SSI structured payloads) — **kept** (migration 0006 dropped only
  `external_news.raw`, which was re-fetchable public HOSE JSON).
- API responses carry the original alongside the English: `title` + `title_en`,
  `category` + `category_en`, `summary` (VI) + `source_language: "vi"`.
- The official HOSE `ViewArticle/{id}` link is on every disclosure (`url` /
  `source_url`), surfaced in the UI as `OFFICIAL SOURCE ↗`. That page is Vietnamese —
  expected and correct.

News row, expanded: English headline · `category_en` · `SOURCE HOSE` ·
`ORIGINAL LANGUAGE VI` · `OFFICIAL SOURCE ↗` · Vietnamese summary (labelled) ·
`Original (Vietnamese): <verbatim title>`.

---

## 7. Accidental EN cleanup

The first two post-recovery `enrich-incremental` runs (before PR #9) inserted **1,177 EN
market-wide rows** (`FUEKIVND` ETF-NAV notices, published 2026-08-21 → 28, a contiguous
id block 196371–197547), against the EN-disabled policy.

Cleanup (in a single transaction, with guards):
```
PRE  vi=81322  non_vi=1177  total=82499
DELETE 1177
POST vi=81322  non_vi=0     total=81322
guards OK: external_news=81322 vi-only; company_events=1150; market_bars=3073; company_profiles=12
```
Pre-delete audit confirmed **all 1,177 target rows were `lang='en'`, `source='HOSE'**.
Post-delete: `external_news` = 81,322, **100% `lang='vi'`**, span unchanged
(2024-09-04 → 2026-08-28); `company_events`, `market_bars`, `company_profiles`,
`user_watchlists` **all unchanged**. No other source or table affected.

---

## 8. Incremental-ingestion verification

`enrich-incremental` after PR #9 + cleanup:

| | this run |
|---|---|
| HOSE languages fetched | **`vi` only** — the response `per_lang` block has no `en` key |
| HOSE vi | inserted **0**, updated 1,146 |
| SSI company events | inserted **0**, updated 57 |
| EN rows | **0 fetched, 0 inserted** |
| `_preflight` | `database is 58.x MB / 280 MB ceiling` — passes, guard active |

Across the three incremental runs performed during verification, **run N>1 inserted zero
rows** — every record matched its deterministic identity key
(`(source, source_id, lang)` for news; `ssi_<sha1>` for SSI events) and updated in place.
Final counts identical to pre-run. **Idempotency proven.**

`coverage` → 30 windows logged, **0 incomplete**, `all_complete: true`. No truncated
windows; the 24-month VI corpus is complete.

Note: each incremental run rewrites ~2,380 rows in place (~1 MB of dead tuples per run,
reclaimed by autovacuum). Benign at any sane cadence; rows are small since `raw` is gone.

---

## 9. DB size / headroom

| | |
|---|---|
| Fresh logical restore (pre-0006) | 55 MB |
| After 0006 + 3 incremental runs + EN cleanup | **`pg_database_size` ≈ 58 MB** |
| PGDATA on disk (`du`) | **147 MB** (data ~82 MB + `pg_wal` ~65 MB) |
| Volume (`df`) | **147 MB / 434 MB used = 34–35%**, **278 MB free** |
| Migration 0006 | `ALTER TABLE external_news DROP COLUMN raw` — catalog-only, `n_tup_upd = 0`, `n_dead_tup = 0` on the table post-migration. **No mass UPDATE, no WAL amplification** (contrast the incident's `SET raw='{}'` on 145k rows). |
| Projected growth | ~3.5 MB/month → ~95 MB (~22%) after 12 months. Target ≤55–60% steady-state **met**. |
| Incident hardening | `cli._preflight(sm)` aborts every write command at/above `ENRICHMENT_DB_SIZE_CEILING_MB` (280 ≈ 65% of 434); `backfill-news` re-checks between windows and stops cleanly (resumable via `source_fetch_log` rows). |

---

## 10. Production smoke

| Check | Result |
|---|---|
| `/health` | `database.connected = true`, `redis_connected = true`, `market_provider = fiinquant` `LIVE` |
| `/healthz` | 200 `{"status":"ok"}` |
| Alembic | **0006** (entrypoint `alembic upgrade head` on every deploy) |
| Dashboard | 5 watchlist rows, `LAST_SESSION` (EOD) provenance as of 2026-08-28 |
| Research / Registry | 3 verified CWs + header filter across ~530 discovered |
| TradingChart / history | HPG 248 daily bars, last close **22,100 @ 2026-08-28**; date-bounded ranges OK |
| Signed-in watchlist | intact — owner `38b4596d-…`, 5 items (CHPG2602, CVPB2615, HPG, VPB, VNINDEX) |
| **News — default view English** | ✓ `DATE · SYMBOL · TYPE · HEADLINE · SOURCE`; every headline + category English; no Vietnamese in the collapsed feed |
| **News — original accessible** | ✓ expand shows Vietnamese summary + `Original (Vietnamese): …` + `OFFICIAL SOURCE ↗` |
| **Event labels English** | ✓ *"New listing"*, *"Insider transaction"*, *"Cash dividend"*, *"Bonus share issue"* … |
| LOAD OLDER | ✓ pages older windows (40 → 80 → …), never the whole corpus |
| SSI company events | ✓ `/events/{sym}` + EVENTS filter |
| HOSE disclosure links | ✓ `ViewArticle/{id}` on every row |
| AI `get_news` / `get_company_events` / `get_corporate_actions` | ✓ grounded in the rescued corpus |
| **AI English default / Vietnamese-on-Vietnamese** | ✓ all four thread scenarios (§3) |
| AI causal restraint | ✓ *"I can describe WHAT the data shows… I don't have news/earnings/foreign flows to explain the cause"* |
| Draggable Orbit anchor | ✓ default clears the docked REPL bar; drag persists to `localStorage`; clamps to viewport |
| Fixed AI conversation panel | ✓ ~380×460, does not resize the terminal (no horizontal scroll) |
| FiinQuant | ✓ **connection generation 1** (single), 5-symbol subscription, both streams connected |
| `provider_direct_reads` / gap-fills | **0 / 0**, `last_gap_fill: null` — no cutover- or language-work-induced gap-fill |
| No EN market-wide ingestion | ✓ `external_news` 100% `lang='vi'` |
| Console errors | **none** on Dashboard, Research, News, instrument panel |

---

## 11. Remaining limitations

1. **AI model.** `minimax/minimax-m3:free` is a weak instruction-follower. The
   language policy holds in every test now, but it relies on three reinforcing mechanisms;
   a stronger model would make (2) and (3) unnecessary. Occasional terse or
   imperfectly-grounded answers on follow-up turns are a model-capability limit, not a
   policy defect.
2. **News headline long tail.** 8.9% of disclosure titles get a leading-verb or category
   classification rather than a specific English disclosure-type phrase. The Vietnamese
   original is always one click away, and the `~` marker / `title_en_exact` flag makes the
   distinction explicit. Coverage can be lifted by adding keyword rules to
   `english.py::_TITLE_RULES` as new patterns appear — no migration, no cost.
3. **Free-text summaries stay Vietnamese.** Per policy, no bulk machine translation of
   81k `summary_html` bodies. They render in the expanded row labelled "original
   Vietnamese". A lazy, per-row-on-view persisted `summary_en` (2 nullable columns) is
   designed in `LANGUAGE_POLICY.md` §2 but deferred — it needs a translation-mechanism
   decision.
4. **English HOSE corpus is deferred, not deleted-forever.** If English coverage is ever
   justified, the scoped path is `backfill-news --lang en` restricted to CW-underlying
   symbols + a recent window — a few thousand rows, not the market-wide feed.
5. **Old `Postgres` service + `postgres-volume-i2ij`** remain online and quiescent (the
   authoritative pre-cutover copy). Keep ≥24 h after cutover; decommission is a separate,
   explicit step — **not done in this work**.
6. **Recurring enrichment scheduling** — `.github/workflows/enrichment-incremental.yml` is
   inert (`workflow_dispatch` only, job guarded on a secret). Activation
   (add `PRODUCTION_DATABASE_URL`, uncomment `schedule:`) is a separate approval gate —
   **not done**.
7. **CODE → Claude Design sync** — not possible via the supported path: the target
   project `1360b08c-…` ("Three trading dashboard directions") is
   `PROJECT_TYPE_PROJECT`, not `PROJECT_TYPE_DESIGN_SYSTEM` (type immutable at creation);
   `DesignSync.list_projects` returns no writable design-system project; the repo is a Vite
   application, not a design-system package the `/design-sync` converter can consume.
   Manual alternative only: update the project in claude.ai/design with current
   screenshots / prompts, or stand up a design-system project after extracting a component
   library (out of scope).
8. **Pre-existing unrelated test failure** —
   `tests/persistence/ingestion/test_backfill.py::test_rerun_without_force_skips_already_covered_chunks`
   fails on `main` (a date-sensitive `market_bars` backfill test, unrelated to Step 14B).
