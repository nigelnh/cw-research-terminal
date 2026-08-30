# Step 14A — Research Data Enrichment: Final Report

**Status:** implemented · deployed · bootstrapped · smoke-tested
**Date:** 2026-08-30
**Commits:** `2305889` (PR #5, merged `b01eb9f`) · PR #6 (AI routing + news category — open)
**Production:** frontend `https://cw-research-terminal.vercel.app` · backend `https://backend-production-626f.up.railway.app`

---

## 1. Audit findings — what already existed

The pre-14A backend was a single FastAPI container (1 uvicorn worker, `numReplicas: 1`, Railway
Free Trial, no card) with:

- **FiinQuant** as the realtime market-data provider: one provider owner, two SignalR
  streams, a 33-symbol subscription cap, Redis warm state, backend WebSocket fan-out.
  A separate historical SDK path with a circuit breaker.
- **PostgreSQL** as the durable store: 7 models (`market_bars` with a `source` column,
  `instrument_snapshots`, `ingestion_state`, `ingestion_runs`, `instruments`,
  `user_watchlists`, `user_watchlist_items`), Alembic chain `0001→0003`.
- **History reads** were already Postgres-first (`history_read_service`), with exactly one
  controlled FiinQuant gap-fill per missing in-horizon range.
- **Instruments**: 533 discovered CWs, of which 5 `VERIFIED_CURRENT`, 1 `CONFLICTING`,
  ~516 `UNKNOWN` (`app/instruments/data/manifest.json`).
- **AI**: a proactive, bounded, read-only tool layer (`ToolExecutor`) — the model does not
  function-call; `resolve_and_execute_proactive_tools` picks tools from query/context
  intent and injects results into the system prompt. Fail-closed metadata verification;
  causal restraint already in the system prompt.
- **No cron, no scheduled jobs.** Ingestion is manual via `python -m app.persistence.cli`.
  The snapshot checkpointer is the only always-on background task.

**Conclusion:** the ingestion pattern to extend was already
`external source → controlled CLI ingestion → normalized Postgres → read API → UI/AI`.
Nothing about the audit suggested restoring n8n or adding an always-on worker.

## 2. Google Drive archive ("n8n & api") findings

Direct Drive access was not available; the recovered candidate inventory from the archive
was treated as **source-discovery + domain/business-rule evidence, not production code**:

- SSI iboard CW master / symbol reference / statistics / corporate actions.
- HSX exchange news + underlying/company reference.
- Simplize analyst-report discovery via Next.js `_next/data/<build-id>/…bao-cao.json`.
- Corporate-action adjustment logic (cash div / stock div / bonus / rights / backward
  cumulative factors) — reimplemented independently as domain reference, never copied.

**Forbidden / non-portable material** (`api.kbsec.com.vn`, `kbbuddywts.kbsec.com.vn`,
KB/KBBuddy credentials, employer-private payload contracts, old tokens, `/KBSV/`-tied
Vietstock routes) was not used, tested, copied, or referenced. Repo hygiene check clean —
no KB/KBBuddy strings, no embedded tokens in source/tests/docs/logs.

## 3. Live viability test — per source

| Source | Endpoint | Result |
|---|---|---|
| **HSX news** | `api.hsx.vn/n/api/v1/{langId}/news` (langId 1=vi 2=en) | ✅ 200 with a plain honest User-Agent. Bounded pagination via `pageIndex`/`pageSize`; server-side `startDate`/`endDate` filtering works (a 30-day window → 42 pages vs 39 468 unfiltered). Newest-first ordering. |
| **VNDirect finfo — events** | `api-finfo.vndirect.com.vn/v4/events?q=code:{SYM}` | ✅ 200. Dividends, meetings, rights, listing/additional-issuance. Events appear twice (`.VN` / `.EN_GB` locale suffix on `id`). |
| **VNDirect finfo — company_profiles** | `.../company_profiles?q=code:{SYM}` | ✅ 200. Exchange, VN/EN name, founding date, tax code, website, employees. No share-count field. |
| **VNDirect finfo — stock_prices** | `.../stock_prices?q=code:{SYM}~date:gte:…~date:lte:…` | ✅ 200. `adClose` (adjusted), `nmVolume`. Used for EOD cross-validation only — never written. |
| **SSI iboard** | `iboard-query.ssi.com.vn/stock/cw/hose` | ❌ **403 server-side** — browser-only bot protection. Not server-ingestable. |
| **Simplize** | `_next/data/<build-id>/…bao-cao.json` | ⏸ Deferred — the build-id in the path rotates on every Simplize deploy; brittle by design. |

Honest User-Agent used throughout:
`cw-research-terminal/1.0 (+https://github.com/nigelnh/cw-research-terminal)` — no browser
spoofing, no bot-wall evasion.

## 4. Sources rejected / deferred and why

- **SSI iboard — rejected.** 403 from a server context regardless of headers; the archive's
  contract is real but the endpoint is only reachable from a real browser session. Pursuing
  it would mean headless-browser scraping — out of scope and fragile.
- **Simplize analyst reports — deferred.** The `_next/data` route depends on an internal
  build hash. A resilient integration needs an HTML-scrape fallback and a build-id probe;
  deferred to a later phase where analyst coverage is the primary goal.
- **A dedicated fundamentals provider (EPS/PE/PB/ROE/margins) — deferred.** No free,
  server-reachable, licence-clean source was found in the time box. The Grid Terminal
  QUANT tab renders these as `—` with a "pending data provider" caption — an honest gap,
  not a fabrication.

## 5. Final source-ownership matrix

| Domain | Owner | Store | Notes |
|---|---|---|---|
| Realtime quotes / ticks | **FiinQuant** (unchanged) | Redis warm state | Untouched by 14A |
| Canonical historical bars | **Postgres-first**, one controlled FiinQuant gap-fill | `market_bars` | Untouched by 14A |
| Contract metadata (strike/ratio/underlying/maturity/LTD) | **instrument manifest**, fail-closed verification | `instruments` | Untouched. News/events never feed this. |
| Exchange & issuer disclosures (news) | **HSX** | `external_news` | New |
| Corporate actions (div/meeting/rights/listing) | **VNDirect finfo** | `corporate_actions` | New. Provenance-recorded; never fed to quant. |
| Company reference (name/exchange/founding/tax) | **VNDirect finfo** | `company_profiles` | New |
| EOD price cross-validation | **VNDirect finfo** (read-only) | — (never written) | New — validation experiment only |

**Source-conflict policy held:** contract-sensitive figures still come only from the
verified instrument manifest. A dividend headline can never rewrite a strike or ratio.

## 6. Chosen architecture + alternatives considered

**Chosen:** a self-contained `app/enrichment/` package in the existing backend repo —

```
external source
  → EnrichmentHttpClient  (bounded timeout, exp-backoff, honest UA, per-attempt fetch log)
  → source clients        (HsxNewsSource, VndirectFinfoSource — hard page cap)
  → pure normalizers      (raw payload → canonical row dict, no I/O)
  → EnrichmentService     (idempotent pg_insert … on_conflict_do_update, xmax insert/update
                           detection, in-batch dedup on the natural key)
  → PostgreSQL            (external_news / corporate_actions / company_profiles / source_fetch_log)
  → repository (read-only) → /api/research/* router  → Grid Terminal NEWS tab + CORP EVENTS
                           → research_tools (get_news / get_corporate_actions) → AI
```

Ingestion is driven by `python -m app.enrichment.cli` (subcommands `news`,
`corporate-actions`, `company-profiles`, `validate-history`, `bootstrap`, `status`).

**Alternatives rejected:**

- **Restore n8n** — the archive used it, but it is an always-on service with material cost
  and a second deployment surface. Code-owned ingestion in the existing repo is simpler and
  has no runtime footprint until invoked.
- **A Railway cron service** — explicitly out of scope for this phase; controlled manual
  production ingestion is enough to validate the architecture.
- **Browser → upstream fan-out** — violates the non-negotiable boundary. The browser only
  ever talks to our backend.
- **Mixed-source price series** — rejected until the cross-validation experiment (§10)
  produced evidence.

## 7. Database / schema changes — Alembic `0004`

Purely additive (`CREATE TABLE` only — non-destructive, zero data-loss risk):

| Table | Natural key | Purpose |
|---|---|---|
| `external_news` | `(source, source_id, lang)` | HSX disclosures. `symbols` JSONB (GIN-indexed), `published_at` index, `summary_html`, `category`, `raw` JSONB. |
| `corporate_actions` | `(source, source_id)` | VNDirect events. `action_type` + `status` CHECK constraints, `(symbol, ex_date)` index, `cash_amount_vnd` NUMERIC(20,4), `ratio_pct` NUMERIC(12,6), `raw` JSONB. |
| `company_profiles` | `symbol` | VNDirect reference. `raw` JSONB. |
| `source_fetch_log` | id | One row per fetch attempt — source, endpoint, symbol, HTTP status, item count, ok, error, duration. `(source, fetched_at)` index. |

Ingestion is idempotent: conflicts `ON CONFLICT DO UPDATE`; `xmax = 0` in the `RETURNING`
clause distinguishes INSERT from UPDATE so runs report inserted-vs-updated counts.
`0004` reached `head` in the container entrypoint on deploy (verified: `alembic current →
0004 (head)`).

## 8. Ingestion architecture properties

- **Idempotent** — deterministic natural keys, upsert, in-batch dedup (the `.VN`/`.EN_GB`
  locale-suffixed VNDirect ids collapse to one row; last write wins).
- **Retry-safe** — bounded exponential backoff (`min(2·2ⁿ, 15) s`) on `{408,425,429,5xx}`;
  non-retryable statuses fail fast. `SourceFetchError` on exhaustion.
- **Resumable** — interrupt mid-run and rerun; upserts converge.
- **Observable** — every attempt writes a `source_fetch_log` row (best-effort; a log-write
  failure never breaks ingestion).
- **Rate-respectful / low-concurrency** — sequential per source, hard page cap
  (`ENRICHMENT_NEWS_MAX_PAGES = 40`).
- **Independent of app startup health** — its own engine + HTTP client; never imported by
  the request path, the market provider, or the lifespan. A source outage cannot affect
  `/healthz`, realtime, quant, the dashboard, Redis, or any core API.

## 9. Production data coverage (post-bootstrap, 2026-08-30)

| Table | Rows | Detail |
|---|---|---|
| `external_news` | **4 000** | 2 000 vi + 2 000 en. Window 2026-08-14 → 2026-08-28 (the 40-page cap truncated the older half of the 30-day request — newest-first, so the recent two weeks are complete). 396 distinct linked symbols; ~98 % of rows carry ≥1 symbol from the title-prefix convention. `category` currently null for all rows — HSX's list endpoint omits `catName` (fix in PR #6, §17). |
| `corporate_actions` | **433** | 12 symbols. LISTING 157 · AGM 119 · CASH_DIVIDEND 63 · OTHER 58 · STOCK_DIVIDEND 23 · BONUS_ISSUE 10 · EGM 2 · RIGHTS_ISSUE 1. Status: CONFIRMED 378 / SCHEDULED 55. `OTHER` at 13 % is the main classifier gap — acceptable for v1; the raw payload is retained in `raw` JSONB for reclassification. |
| `company_profiles` | **12 / 12** | All bootstrap symbols resolved. |
| `source_fetch_log` | **108** | **100 % ok**, zero failures across HSX news (80) + VNDirect events (12) + profiles (12) + validate-history (4). |

Bootstrap universe: `HPG VPB TCB VHM VNM MWG FPT MSN SSI STB MBB VIC`.

## 10. Historical-source comparison — can FiinQuant historical demand be reduced?

`validate-history --symbols HPG,VPB,TCB,VHM --days 40`, comparing VNDirect `adClose`
against the production canonical series (`/api/market/history`, Postgres-first, adjusted):

| Symbol | Sessions compared | Close exact-match | Max volume delta |
|---|---|---|---|
| HPG | 29 | **29 / 29 (100 %)** | 0.31 % |
| VPB | 29 | **29 / 29 (100 %)** | 0.10 % |
| TCB | 29 | **29 / 29 (100 %)** | 0.24 % |
| VHM | 29 | **29 / 29 (100 %)** | 0.74 % |

**Adjusted close is an exact match.** Volume differs ≤0.74 % (`nmVolume` = matched
order-book volume vs the canonical total — a definitional difference, not an error).

**Finding:** VNDirect EOD is validation-grade for **adjusted close** on liquid HOSE equities.
It is a safe **backfill / cross-check** source for closing prices — e.g. seeding Postgres
coverage for a new underlying so the first chart request is a DB hit instead of a FiinQuant
gap-fill. It is **not** yet proven for intraday, OHLC-completeness, or low-liquidity names,
so the recommendation is **narrow**: use it to widen Postgres close-price coverage
(reducing gap-fills), not to replace the canonical series. No mixed series were introduced
in this phase.

## 11. Product / UI changes

- **NEWS tab** — a third top-level tab (`?tab=news`). Grid Terminal dense mono table
  `TIME · SYMBOL · CATEGORY · HEADLINE`; row click expands the summary + a `SOURCE` line;
  `?q=` filters by ticker (bare-ticker token) or free-text headline; honest empty
  ("No disclosures ingested yet") and error states; a standing caption
  *"disclosed near the stated time — timing only, not causation."* Symbol chips are
  clickable → select the instrument.
- **Instrument panel → QUANT → CORP EVENTS** — the previously-stubbed table is wired to
  `/api/research/corporate-actions/{symbol}`. Columns `EVENT TYPE · EX-DIV · ISSUE · DESC`
  with real rows (e.g. HPG: `STOCK DIV · 2026-05-25 · 100:10`, `CASH DIV · 2026-05-11 ·
  500 đ/sh`, `AGM · 2026-04-21`). Caption updated to
  *"fundamentals: pending data provider · corp events: disclosed timing only, not
  causation."*
- **Data hooks / client** — `useResearchNews`, `useCorporateActions` (TanStack Query, one
  key per symbol/query/lang), `backendClient.getResearchNews / getCorporateActions /
  getCompanyProfile`, domain types in `domain/models/research.ts`.

Verified in production: NEWS tab renders real HSX disclosures with linked symbols; `?q=VPB`
narrows to VPB-prefixed items; CORP EVENTS shows real HPG events; **the browser calls only
`backend-production-626f.up.railway.app/api/research/*`** — no `hsx.vn` or `vndirect.com.vn`
request originates from the page (network trace confirmed).

## 12. News / event architecture

- `external_news` — one row per `(source, source_id, lang)`. Symbol linkage is derived
  from the HOSE title-prefix convention (`MSH: …` → `["MSH"]`; dotted compound CW codes
  `VHM.LPBS.…: …` → `["VHM"]`; sentence-like prefixes rejected). GIN index on `symbols`
  for `@>` containment queries.
- `corporate_actions` — classified into a small explicit vocabulary
  (`CASH_DIVIDEND / STOCK_DIVIDEND / BONUS_ISSUE / RIGHTS_ISSUE / AGM / EGM / LISTING /
  DELISTING / OTHER`) with a `SCHEDULED / CONFIRMED / CANCELLED / UNKNOWN` status, from
  VNDirect `type` / `group` / `note` text. Dates mapped to `ex_date` / `record_date` /
  `payment_date` / `disclosure_date`.
- Read API cursor-paginates news by `published_at`; a `news/facets` endpoint returns the
  most-frequent symbols for a filter affordance.

## 13. AI tools / context changes

Two bounded read-only tools, PostgreSQL-only, schema-validated, clamped
(`AI_NEWS_MAX_RESULTS = 12`, `AI_CORPORATE_ACTIONS_MAX_RESULTS = 12`):

- `get_news(symbol?, limit?, lang="vi")`
- `get_corporate_actions(symbol, limit?)`

Every payload carries `provenance: "RESEARCH_ENRICHMENT"` and a `causal_note`
("disclosed/effective near the stated dates — do not assert they caused any price
movement"). `status: "UNAVAILABLE"` when the store is not configured; `INVALID_ARGUMENT`
when `symbol` is missing.

**Gap found and fixed (PR #6):** the tools were in the registry but the production AI path
is proactive-only — `ToolExecutor` had no branch for them, so a *"list HPG dividends"* chat
answered *"I don't have that data."* PR #6 adds `NEWS_KEYWORDS` / `CORP_ACTION_KEYWORDS`
(EN + VI) intent routing (resolved symbol + corp-action intent → `get_corporate_actions`;
+ news intent → `get_news`; news intent or the NEWS page with no symbol → `get_news({})`),
activity labels, and a system-prompt block mapping `RESEARCH_ENRICHMENT` provenance with
the causal restraint + the SCHEDULED/CONFIRMED distinction. Contract-sensitive terms still
come only from `get_instrument`.

Verified locally: `"what dividends has VPB had?"` → `get_quote` + `get_corporate_actions`;
`"cổ tức của FPT năm nay?"` → `get_corporate_actions`; `"is HPG up today?"` → `get_quote`
only (no false positive). Live production verification pending the PR #6 deploy.

## 14. FiinQuant before / after impact

| Signal | Before 14A | After 14A + bootstrap | Verdict |
|---|---|---|---|
| `market_provider` | `fiinquant` | `fiinquant` | unchanged |
| Provider lifecycle (`generation`) | 1 | **1** | no re-instantiation |
| Subscription set | `CHPG2602, CVPB2615, HPG, VNINDEX, VPB` (5) | same (5) | unchanged, well under 33 |
| `history_reads.provider_direct_reads` | 0 | **0** | no historical FiinQuant calls |
| `history_reads.gap_fills_attempted` | 0 | **0** | no gap-fills triggered |
| `quant_scheduler.failures` | 0 | 0 | unchanged |
| Off-session reconnect | paced 300 s (`session_active=False`) | paced 300 s — logged disconnect 20:41:24 → reconnect 20:46:26 | unchanged (documented pre-existing behavior) |

The `SignalRCoreClient: NoHeaderException` ERROR lines are the documented off-hours
socket-close artifact that triggers the paced reconnect (DEPLOYMENT_CHECKPOINT.md, `63009aa`).
The enrichment package never imports `market_subscription_manager`, `fiinquant_provider`,
or any SignalR code. **Step 14A introduced zero FiinQuant realtime or historical traffic.**

## 15. External-request behavior / cost

- **Who calls upstream:** only the enrichment CLI, only when a human runs it. The browser
  never does; read APIs never do; AI tools never do.
- **Bootstrap volume:** ~108 upstream requests total (80 HSX news pages + 12 VNDirect
  events + 12 profiles + 4 validate-history), all 200, ~0.3–1.5 s each.
- **Infra cost:** zero new services, no Railway plan change, no payment method. Storage:
  4 000 news + 433 events + 12 profiles + 108 log rows ≈ a few MB of Postgres (well within
  the 500 MB volume; total volume 84 MB / 500 MB).
- **Railway usage** this period remains ~$0.006 (Free Trial, no card).

## 16. Automated test results

- **Backend:** +41 deterministic tests (fixtures + ephemeral Postgres cluster; no live
  network in the suite). Normalization (title→symbol, HTML strip, epoch dates, event
  classification, profile), source clients (pagination + hard cap, transient-retry,
  non-retryable failure isolation), upsert idempotency + in-batch dedup, repository
  filters/ordering/facets, AI-tool bounds + `causal_note` + `INVALID_ARGUMENT` +
  `UNAVAILABLE`, read-API empty-vs-populated, executor tool-routing (+ no-false-positive),
  system-prompt provenance/causal-restraint. Full suite **1 017 pass** / 20 skip / **1
  pre-existing failure** (`test_backfill.py::test_rerun_without_force_skips_already_covered_chunks`
  — date-arithmetic, breaks near month boundaries, verified identical on `main`, unrelated
  to 14A). `pyright app` — 0 errors.
- **Frontend:** +4 UI tests (NEWS feed render / empty state / symbol filter; CORP EVENTS
  wired). `tsc --noEmit` clean, **218 vitest pass**, `vite build` OK.

## 17. Production smoke results

| Check | Result |
|---|---|
| Railway deployed the merged commit | ✅ `/api/research/*` routes live (didn't exist pre-merge) |
| Alembic `0004` at head | ✅ `alembic current → 0004 (head)`; all 4 tables present |
| Production bootstrap | ✅ 4 000 news + 433 corporate actions + 12 profiles; `source_fetch_log` 100 % ok |
| NEWS tab | ✅ real HSX disclosures, symbol chips, `?q=VPB` filter, row expand, honest empty state |
| CORP EVENTS panel | ✅ real HPG events (LISTING / STOCK DIV / CASH DIV / AGM) with dates + ratio/amount |
| AI `get_news` / `get_corporate_actions` vs real data | ⚠️ tools return correct real rows when invoked directly (`get_corporate_actions('VPB')` → 6 events with `causal_note` + `provenance`); **not yet reachable from `/api/ai/chat`** — fixed in PR #6, pending deploy |
| Browser → upstream isolation | ✅ network trace: only `…/api/research/*` calls; no `hsx.vn` / `vndirect.com.vn` |
| FiinQuant unchanged | ✅ generation 1, 5-symbol subscription, 0 provider reads, 0 gap-fills |
| Dashboard / realtime | ✅ unchanged; charts still Postgres-first (0 `provider_direct_reads`) |

**Issues found → fixed via PR:** (1) AI tools dead in the live path; (2) news `category`
always null. Both in PR #6 (`fix/step-14a-ai-tool-routing-and-news-category`) — no
migration; re-run `cli news --days 30 --lang vi --lang en` after merge to backfill
categories on the existing 4 000 rows (idempotent UPDATE).

## 18. Remaining limitations

- **News window truncation** — the 40-page cap stops a 30-day request at ~2 000
  items/lang (≈2 recent weeks in a busy H1-report season). Raise `ENRICHMENT_NEWS_MAX_PAGES`
  or iterate date-windowed sub-requests for full historical coverage.
- **News `category`** — populated only after PR #6 (bounded detail fetch per `(lang, catId)`).
- **`OTHER` corporate actions at 13 %** — the classifier is text-heuristic; unusual
  VNDirect `type` values fall through. Raw payload retained for reclassification.
- **No deep-link URL for HSX news** — `alias` is null even on the detail endpoint; the
  public portal is a slow SPA. The expand panel shows the summary + source, no external link.
- **No fundamentals provider** — EPS/PE/PB/ROE/margins remain `—`.
- **VNDirect EOD** proven only for adjusted close on liquid names — not intraday, not
  OHLC-complete, not low-liquidity.
- **No scheduler** — ingestion is manual (`railway ssh -s backend -- python -m
  app.enrichment.cli …`). By design for this phase.
- **Company profile share counts** — VNDirect `company_profiles` has no listed/outstanding
  share field; `listed_shares` / `outstanding_shares` are null.

## 19. Recommended Step 14B (evidence-based)

Only items the 14A evidence actually supports:

1. **Close-price backfill from VNDirect** — proven exact-match. A `cli enrich-history`
   subcommand that seeds `market_bars` (`source = 'vndirect_eod'`) for underlyings with
   thin Postgres coverage, measured against the gap-fill counters, to quantify the
   FiinQuant historical-call reduction.
2. **News completeness** — date-windowed pagination + a larger cap; a `cli news --backfill`
   mode; category resolution folded in (from PR #6).
3. **Corporate-action classifier v2** — drive the `OTHER` rate down using the richer
   `type` / `typeDesc` vocabulary now visible in `raw`; add `numberOfShares` extraction.
4. **A fundamentals source** — evaluate a licence-clean provider for the QUANT tab's
   `FINANCIAL INDICATORS` block (currently all `—`).
5. **Analyst-report discovery (Simplize)** — with an HTML-scrape fallback + build-id probe,
   if analyst coverage becomes a priority.
6. **Scheduling** — only if 14B needs freshness guarantees; a Railway cron service is a
   paid-infra decision for the user, not an automatic step.

**Do not** pursue SSI iboard server-side, mixed intraday price series, or an n8n runtime —
the evidence is against all three.
