# Language policy — source vs. product vs. AI

CW Research Terminal is an **English-first product** built on **Vietnamese-canonical
sources**. Those are two different axes and must never be conflated.

| Axis | Value | Why |
|---|---|---|
| **Source language** (ingestion) | **Vietnamese is canonical** for HOSE. | The HOSE `langId=1` (vi) feed has the full, useful coverage. `langId=2` (en) is **not** a 1:1 localization — it has disjoint `source_id`s, ~21 months vs 24, and is dominated by ETF-NAV / foreign-holding notices. Re-crawling EN market-wide adds noise, not value. SSI / VNDirect events are Vietnamese at source too. |
| **Product language** (every user-facing surface) | **English.** | Navigation, labels, table headers, filters, empty/error states, News, Research, instrument panels, generated summaries. Vietnamese appears **only** as explicitly-marked original-source content. |
| **AI language** | **English by default.** Vietnamese **only** when the user's own latest substantive message is Vietnamese; back to English the moment they switch. Never inferred from thread history, retrieved DB text, or the selected symbol. |

"VI is the canonical HOSE **source** feed" is a data-ownership decision. It does **not**
mean the product is Vietnamese.

---

## 1. Audit — production state (2026-08-30)

### 1a. UI chrome — ✅ already English

Verified in production (`cw-research-terminal.vercel.app`): header (`CW-TERM`,
`DASHBOARD` / `RESEARCH` / `NEWS`, `/ filter or jump to symbol`, clock, `CLOSED`,
`SIGN IN`), `WATCHLIST` + all column headers (`SYMBOL REF BID ASK TRD +/- CHG% VOLUME
FRN BUY/SELL/ROOM`, CW table `STRIKE RATIO DTE IV BID/TRD/ASK`), `REGISTRY`
(`ISSUER UNDERLYING MATURITY STATUS`, `TRACKED` / `REFERENCE`), `NEWS`
(`DATE SYMBOL KIND CATEGORY HEADLINE`, `ALL` / `DISCLOSURES` / `EVENTS`,
`ALL SRC` / `HOSE` / `SSI` / `VND`, `LOAD OLDER`), instrument panel
(`OVERVIEW` / `QUANT`, `TIME & SALES`, `THEO PRICE`, `MONEYNESS S/K`, greeks),
empty states ("Time & sales unavailable outside a live session", "Order book depth
& time-of-sale unavailable outside a live session"), AI REPL placeholder
("ask about pricing, greeks, contract terms, disclosures or events…"),
`RESEARCH ASSISTANT`. **No Vietnamese UI chrome anywhere.**

### 1b. News / event data — ❌ Vietnamese leaks into product surfaces

| Surface | Field | Current | Problem |
|---|---|---|---|
| News `CATEGORY` | `external_news.category` | `Tin Tổ chức niêm yết`, `Tin quản lý thị trường`, … | raw HOSE `catName` — Vietnamese |
| News `HEADLINE` | `external_news.title` | `HPG: Báo cáo tình hình quản trị 6 tháng đầu năm 2026` | raw HOSE title — Vietnamese |
| News expand row | `external_news.summary_html` | Vietnamese paragraph | raw HOSE summary |
| News `EVENTS` rows | `company_events.event_name` | `MBB · Giao dịch nội bộ: Giao dịch tổ chức` | `event_class` is English (`OWNERSHIP`) but the trailing detail is Vietnamese |

`event_class` / `event_type` are **already English enums** (`DIVIDEND`, `FINANCIAL`,
`LISTING`, `MEETING`, `OWNERSHIP`, `RIGHTS`, `OTHER` / `CASH_DIVIDEND`,
`FINANCIAL_STATEMENT`, `AGM`, …). Dates, amounts, ratios, statuses are language-neutral.
The gap is **free-text**: news `title` / `summary` / `category`, and event `event_name` / `note`.

### 1c. AI responses — ⚠️ English default is not robust

| Scenario | Observed | Verdict |
|---|---|---|
| Fresh thread, English question ("What recent disclosures has HPG had?") | **English answer**, VI disclosure titles translated on the fly ("Six-month corporate governance report (H1 2026)", "Q2 2026 business results announcement"), proper nouns kept, provenance + causal restraint intact | ✅ correct |
| Thread with prior Vietnamese turns, then an English question ("Why did VPB go up today?") | **Vietnamese answer** — model followed the thread's dominant language, not the latest message | ❌ wrong |

Root cause: the system prompt said *"Always match the language of the user's message"* —
ambiguous when the thread is mixed, and the free model (`minimax/minimax-m3:free`)
weights thread history over the latest turn. **Fixed** (this change): the rule is now
"English by default; Vietnamese only when the user's **own latest substantive message**
is Vietnamese; never inferred from thread history, retrieved text, or the selected symbol;
when answering in English from Vietnamese sources, translate/paraphrase, keep proper
nouns and provenance, invent nothing, preserve causal restraint."

The AI already **translates VI source content into English inline** when the
conversation is English — no separate translation infrastructure is needed for the AI path.

---

## 2. English-presentation layer for News / events — design

Constraints (from the product owner): **no paid translation API**, **no new paid
infra**, **no bulk-LLM pass over 81,322 rows**, **no per-request dynamic translation**,
**never destroy the Vietnamese source**, **never hide provenance**, **never pass a
machine-normalized English title off as the original HOSE wording**.

### 2a. What the corpus allows (measured on the 81,322-row VI corpus)

| Layer | Distinct values | Concentration | Deterministic English? |
|---|---|---|---|
| `external_news.category` (HOSE `catName`) | **~31** | top 3 = **97%** (`Tin Tổ chức niêm yết` 69%, `Tin quản lý thị trường` 28%, `Tin về hoạt động của Sở` 1%) | **100% — a hand-written dictionary** |
| `company_events.event_class` / `event_type` | 7 / ~13 | — | **already English** |
| `company_events.event_name` | small (few dozen SSI phrasings) | — | **~100% — a dictionary** |
| `external_news.title` head (phrase after `SYMBOL:`) | ~11,900 distinct, Zipf tail | top 20 heads = **42%**, top 50 = **51%**, top ~250 ≈ **70%+** | **partial — a template/prefix dictionary** covers the common patterns; the long tail does not |
| `external_news.summary_html` | free text | — | **not deterministically** |

HOSE disclosure titles are extremely templated — e.g.
`Thông báo thay đổi giá trị tài sản ròng ngày …` (8,748), `Thông báo về danh mục
chứng khoán cơ cấu hoán đổi …` (8,033), `Báo cáo kết quả giao dịch cổ phiếu của
người nội bộ …` (826). A curated prefix table of ~150–250 patterns →
`SYMBOL: <English template> <date/number tail passed through>`.

### 2b. Recommended design — **(A) + (C)**, layered, deterministic, zero-cost

**Layer 1 — normalized English labels (deterministic dictionary, ship first).**
- `category_en`: 31-entry `dict` → e.g. `Tin Tổ chức niêm yết` → *"Listed-issuer disclosure"*,
  `Tin quản lý thị trường` → *"Market administration notice"*, `Tin tức CW` → *"Covered-warrant news"*.
- `event_name_en`: dictionary over the SSI/VNDirect `event_name` phrasings.
- Both live as pure functions in `app/enrichment/normalize.py` (no I/O, unit-tested),
  applied at **read time** in the repository/serializer — **no migration, no backfill**,
  works for every existing row instantly. A row whose category is unmapped falls back
  to the English `event_class` / a generic "HOSE disclosure".

**Layer 2 — English headline (template dictionary + honest fallback).**
- `title_en`: an ordered list of `(vi_prefix_regex, en_template)` covering the top
  patterns. Match → English headline with the numeric/date tail passed through verbatim
  (`Thông báo thay đổi giá trị tài sản ròng ngày 27/08/2026` → *"Net asset value change
  notice, 27/08/2026"*).
- **No match** → **honest classification**, never a fake translation:
  `"{English category} — {SYMBOL}"` (e.g. *"Listed-issuer disclosure — VSC"*), or the
  `event_class` for events.
- The response always carries **both**: `title_en` (or the honest fallback) **and**
  `title` (the untouched Vietnamese original), plus `title_en_exact: false` whenever
  Layer 2 produced a template/fallback rather than a verified translation.

**Layer 3 — original-source access (already mostly there).**
- `url` → the HOSE `ViewArticle/{id}` portal page (Vietnamese — that is fine and expected).
- `source: "HOSE"`, add `source_language: "vi"`.
- The Vietnamese `title` / `summary_html` stay in the row **forever** as provenance.

**Optional Layer 4 — lazy persisted English summary (design only, not now).**
If a full English *summary* is ever wanted: add nullable `summary_en` +
`summary_en_source` columns, populate **lazily** the first time a row is opened in the
detail view, cache the result, never batch. Deferred — needs a translation mechanism
decision and is out of scope until the deterministic layers are shipped and assessed.

### 2c. Rejected

- ❌ Paid translation API / bulk LLM over 81k rows / per-request dynamic translation — forbidden.
- ❌ Overwriting `title` / `summary_html` with English — destroys source evidence.
- ❌ Showing only the English template with no original — hides provenance and misrepresents a machine label as the filing's wording.
- ❌ Reverting the product to Vietnamese because a perfect translation of every old row isn't free — an honest English classification + one click to the Vietnamese original is the correct trade.

### 2d. Proposed API / UI shape

```
GET /api/research/feed → each item:
  title_en        "Six-month corporate governance report — HPG"   # display
  title_en_exact  false                                            # template/fallback, not a verified translation
  title           "HPG: Báo cáo tình hình quản trị 6 tháng đầu năm 2026"   # original, untouched
  category_en     "Listed-issuer disclosure"
  category        "Tin Tổ chức niêm yết"
  source          "HOSE"
  source_language "vi"
  url             "https://www.hsx.vn/Modules/CMS/Web/ViewArticle/2493262"
```

News row: **English `title_en` as the headline**, `category_en` in the CATEGORY column;
the expand row shows `SOURCE: HOSE · ORIGINAL LANGUAGE: VI · OFFICIAL SOURCE ↗` and the
verbatim Vietnamese `title` / `summary` under an "Original (Vietnamese)" label.

### 2e. Scope / effort

| Piece | Size | Migration? |
|---|---|---|
| AI system-prompt English-first rule | **done (this change)** | no |
| `category_en` + `event_name_en` dictionaries + read-time wiring + tests | small (~1 day) | **no** |
| `title_en` template dictionary (top ~200 patterns) + fallback + tests | medium (~2–3 days, mostly curating patterns) | **no** |
| `source_language` field + feed serializer + News UI (headline/category/original block) | small–medium | no (additive field) |
| Layer 4 lazy `summary_en` | deferred | yes (2 nullable cols) |

Layers 1–3 are **additive, migration-free, zero-cost, deterministic**. They are a
bounded piece of work, not a feature phase — but they are **not yet built**; this
document is the design + the product owner's go/no-go gate.

---

## 3. Step 14B report — language section (to fold into the final report)

- **Source language:** Vietnamese is the canonical HOSE ingestion feed (full coverage;
  EN is disjoint + noisy). SSI/VNDirect events are Vietnamese at source. EN market-wide
  ingestion stays **disabled** — `enrich-incremental` / `bootstrap` default to
  `ENRICHMENT_INCREMENTAL_HOSE_LANGS=vi`; a deliberate EN pull is still an explicit
  `backfill-news --lang en`.
- **Product language:** English-first on every user-facing surface. UI chrome is already
  fully English. Data free-text (News title/summary/category, event_name) still surfaces
  Vietnamese — closed by the deterministic English-presentation layer in §2 (designed,
  gated on product-owner approval).
- **AI language:** English by default; Vietnamese only when the user's own latest
  substantive message is Vietnamese. Never inferred from thread history, retrieved
  source text, or the selected symbol. Enforced in `ai_system_prompt.py`
  (`test_system_prompt_enforces_english_first_language_policy`). VI source → English
  answer with translation + retained provenance + causal restraint (already observed
  working in production for clean-English threads).
