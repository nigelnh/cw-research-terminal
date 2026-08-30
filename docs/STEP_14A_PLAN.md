# Step 14A — Research Data Enrichment Architecture (plan)

_Implementation-discipline plan. The final report is the authoritative decision document._

## Audit summary

- **Registry**: local `active_warrants.json` snapshot — 533 discovered CWs, only **5
  VERIFIED_CURRENT** with full terms + provenance, 1 CONFLICTING, **516 UNKNOWN**
  (dchart-discovered symbols, no contract terms). Fail-closed quant gate.
- **History**: Postgres-first (`market_bars`, `source` column already present) with **one
  controlled FiinQuant gap-fill** per missing in-horizon range. More Postgres coverage ⇒
  fewer FiinQuant historical calls. ~2.6k bars, ~12 symbols, latest 2026-08-28.
- **Deployment**: Railway, single container / single worker / 1 replica, Free Trial (no
  card). **No cron service, no scheduled jobs.** Manual ingestion via
  `python -m app.persistence.cli`. Snapshot checkpointer is the only always-on task.
- **AI tools**: 7 bounded read-only tools; causal-restraint + prompt-injection guards in place.

## Live source viability (benign server-side tests, `User-Agent: cw-research-terminal/1.0`)

| Source | Endpoint | Result |
|---|---|---|
| **VNDirect finfo** | `api-finfo.vndirect.com.vn/v4/{stock_prices,vnmarket_prices,events,company_profiles,stocks,ratios,financial_statements}` | **200, JSON, paginated (`totalElements`/`totalPages`), no auth, no bot-wall** |
| **HSX news** | `api.hsx.vn/n/api/v1/{1\|2}/news` (list) + `/{1}/news/{id}` (detail) | **200, JSON, `paging.totalCount`/`totalPages`, VN+EN, `startDate`/`endDate` filter, symbol via title prefix** |
| **VNDirect dchart** | `dchart-api.vndirect.com.vn/dchart/search` | already used for discovery — keep |
| SSI iboard | `iboard-query/api.ssi.com.vn` | **403 Blocked** — browser-only bot protection; not server-ingestable |
| Simplize | `_next/data/<build-id>/…bao-cao.json` | brittle by design — **deferred** |

### History cross-validation (VNDirect `stock_prices` adClose vs production canonical)
HPG / VPB / TCB / VHM, last 10 completed sessions: **close prices exact match (100%)**;
volume differs ~0.1–0.3 % (VNDirect `nmVolume` = matched-order only vs FiinQuant total).
Session dates align with the VN calendar. No corporate-action discontinuities in-window.
⇒ VNDirect EOD is **validation-grade for price**, **secondary-seed grade for new coverage**.

## Source-ownership matrix

| Domain | PRIMARY | SECONDARY / VALIDATION | Notes |
|---|---|---|---|
| realtime trade / bid-ask | FiinQuant | — | unchanged |
| historical OHLCV (daily) | FiinQuant | VNDirect `stock_prices` (VALIDATION now; seed candidate 14B) | prices exact; do not overwrite FiinQuant bars |
| CW contract terms | manual reconciliation | — | fail-closed philosophy preserved; no automated authoritative source exists |
| CW identity / lifecycle | manual | VNDirect `v4/stocks` (VALIDATION) | isin, listed/delisted, issuer, underlying, `status` — never feeds quant |
| stock/company reference | VNDirect `company_profiles` | — | new domain |
| corporate actions | VNDirect `v4/events` | — | new domain, structured (dividend amount, ratio, ex/record dates) |
| exchange news / disclosures | HSX `news` | — | new domain |
| analyst reports | — | — | deferred |
| index breadth | VNDirect `vnmarket_prices` | — | EXPERIMENTAL, not surfaced this phase |

## Scope for 14A (3 integrations + 1 validation experiment)

1. **Exchange news** — HSX → `external_news` + adapter + CLI + `GET /api/news` + **NEWS tab**
   (Grid Terminal dense table) + `get_news` AI tool.
2. **Corporate actions** — VNDirect `v4/events` → `corporate_actions` + adapter + CLI +
   `GET /api/corporate-actions` + wire the instrument-panel `CORP EVENTS` table to real data
   + `get_corporate_actions` AI tool.
3. **Company reference** — VNDirect `company_profiles` → `company_profiles` + adapter + CLI +
   `GET /api/company/{symbol}` + light instrument-context use.
4. **History validation** — VNDirect `stock_prices` → CLI `validate-history` +
   `source_fetch_log` audit + a report quantifying FiinQuant parity. No auto-seed this phase.

Deferred to 14B: VNDirect history seeding into Postgres, full fundamentals ratios (EPS/PE/PB
for the FINANCIAL INDICATORS panel), analyst reports, scheduled ingestion.

## Schema (Alembic `0004`)

- `external_news(source, source_id UNIQUE, lang, title, summary_html, category, symbols
  jsonb, related_source_id, published_at tstz, approved_at tstz, url, observed_at, raw jsonb)`
- `corporate_actions(source, source_id UNIQUE, symbol, action_type, status, ex_date,
  record_date, payment_date, disclosure_date, cash_amount_vnd, ratio_pct, ratio_text,
  dividend_year, note, url, observed_at, raw jsonb)`
- `company_profiles(symbol UNIQUE, exchange, vn_name, en_name, industry, found_date,
  tax_code, website, listed_shares, outstanding_shares, source, source_id, observed_at, raw)`
- `source_fetch_log(source, endpoint, symbol, http_status, item_count, ok, error,
  duration_ms, fetched_at)` — lightweight external-fetch audit.

All: idempotent upsert on the natural key, `raw` jsonb for auditability, timestamptz.

## Ingestion architecture

- `app/enrichment/` — `vndirect_client.py`, `hsx_client.py` (httpx, bounded timeouts,
  retry, pagination caps), `normalize.py`, `service.py` (upsert), `cli.py`.
- CLI: `python -m app.enrichment.cli {news|corporate-actions|company-profiles|validate-history}`.
- Zero app-startup coupling. A source failure cannot affect `/healthz`, realtime, quant,
  or core APIs (read APIs are Postgres-only).
- No new FiinQuant traffic. Browser never contacts an upstream source.

## Non-negotiables preserved

- FiinQuant: one owner, two SignalR streams, 33-symbol cap, Redis warm state, WS fan-out —
  untouched. Verified before/after: realtime connection count, provider reads.
- Contract-sensitive data (strike/ratio/underlying/maturity/LTD): fail-closed; conflicts are
  provenance-recorded, never silently fed to quant.
- AI: Postgres-backed reads only, bounded, schema-validated, no upstream calls, causal
  restraint ("disclosed near this period", never "caused").

## Bootstrap (production, controlled)

- News: last 30 days of HOSE disclosures (VN + EN), bounded page walk.
- Corporate actions: research/demo universe + active-CW underlyings (~12 symbols), full history.
- Company profiles: same universe.
- History validation: HPG/VPB/TCB/VHM — record parity.

## Gates

backend: `pytest`, `pyright app`, no KB/employer deps, no embedded tokens.
frontend: `tsc --noEmit`, `vitest`, `vite build`.
Then: safe migration, controlled production ingestion, production smoke, fix issues.
