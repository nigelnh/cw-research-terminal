# Covered-warrant contract metadata — provenance & verification

Independently written from public sources. No proprietary data.

## Why this exists

The quant engine prices a covered warrant from its **effective contract terms**:
underlying, exercise (strike) price, exercise ratio, and maturity date. If those are wrong,
every downstream number (theoretical price, implied volatility, all five Greeks, moneyness)
is wrong. So the engine refuses to publish analytics for a warrant whose terms are not
**verified against an auditable public source**.

## The model (already in the code)

`app/instruments/instrument_schemas.py`

| Dimension | Values | Meaning |
|---|---|---|
| `status` (lifecycle) | `ACTIVE` / `EXPIRED` / `UNKNOWN` | Is the contract live? |
| `data_quality` | `COMPLETE` / `PARTIAL` | Are strike, ratio and maturity all present? |
| `evidence_level` | `CURRENT_EXCHANGE_LIST` / `CURRENT_BROKER_MARKET_LIST` / `CURRENT_PROVIDER_LIST` / `MANUAL_SNAPSHOT` / `SEARCH_ONLY` / `EXPIRED_BY_DATE` | How do we know the lifecycle status? |
| `metadata_verification` | `VERIFIED_CURRENT` / `CONFLICTING` / `STALE` / `UNVERIFIED` | Grade of the contract-term values themselves |

`metadata_verification` distinguishes:

- **field exists** — it is non-null in the snapshot
- **field is current** — the value reflects the live contract, including any
  corporate-action adjustment
- **field is verified from an acceptable source** — there is a `provenance` block with a
  concrete, auditable reference (`source_url` and/or `source_document_id`)
- **field is stale** — the provenance `retrieved_at` is older than
  `INSTRUMENT_METADATA_MAX_AGE_DAYS` (default 120); `VERIFIED_CURRENT` auto-downgrades to
  `STALE` at load time and the quant gate then rejects it until re-reconciled
- **field is partial** — one or more of strike / ratio / maturity is missing
  (`data_quality = PARTIAL`)

## The quant gate

`app/quant/quant_engine.py` rejects, in order, with an explicit reason:

1. not in registry → `INSTRUMENT_NOT_IN_REGISTRY`
2. `status != ACTIVE` → `LIFECYCLE_NOT_ACTIVE`
3. `data_quality != COMPLETE` → `METADATA_INCOMPLETE`
4. `metadata_verification != VERIFIED_CURRENT` → `METADATA_NOT_VERIFIED_CURRENT`
5. strike / ratio / maturity invalid → `INVALID_STRIKE_PRICE` / `INVALID_EXERCISE_RATIO` / `MISSING_MATURITY_DATE`
6. past maturity → `INSTRUMENT_EXPIRED`
7. no underlying spot price → `UNDERLYING_SPOT_PRICE_UNAVAILABLE`
8. past last trading date → `NOT_TRADABLE (PENDING_MATURITY / EXPIRED)` — greeks/IV are cleared

There is **no per-symbol bypass**. A warrant shows analytics only by passing every step.

## Allowed sources

- The current legitimate FiinQuant integration — **only** where the account entitlement
  actually exposes the field. (`session.BasicInfor(...)` returns HTTP 403 for this account,
  so FiinQuant is **not** a source for contract terms here.)
- HOSE / public exchange listing information.
- The existing public instrument-discovery source (VNDirect `dchart` public search) — used
  for symbol discovery only (`evidence_level: SEARCH_ONLY`), never for terms.
- Public market-data aggregators (Vietstock, 24hMoney) — manually reconciled, recorded with
  the exact page URL and retrieval date in `provenance`.

Never: KBSV, KBBuddy, the old `hq_gui` proprietary data, internal company endpoints, or
cached private payloads.

## Refresh / re-verification workflow

1. For each demo / actively-priced CW, open the two public aggregator pages and read the
   contract table.
2. Reconcile: issuer, underlying, strike, ratio (initial **and** adjusted), maturity,
   last-trading date, listed volume, issue price.
3. If both sources agree and no corporate-action adjustment is ambiguous →
   `metadata_verification: VERIFIED_CURRENT`, with a `provenance.initial_terms_source` and a
   corroborating `provenance.effective_terms_source`, each carrying `source_url` +
   `retrieved_at`.
4. If the sources disagree, or a corporate-action adjustment can't be pinned to one
   authoritative value → `CONFLICTING`. Record why in the provenance notes. The gate keeps
   the warrant dark.
5. `retrieved_at` older than `INSTRUMENT_METADATA_MAX_AGE_DAYS` → the loader auto-marks it
   `STALE`; repeat steps 1–3 to renew.

This is deliberately a small manual reconciliation, not a crawler. It is exercised for the
handful of CWs the demo actually prices.

## Current demo symbols (as of 2026-08-29)

### CVPB2615 — `VERIFIED_CURRENT`

| Field | Value | Source | As-of | Method |
|---|---|---|---|---|
| issuer | ACBS (Công ty TNHH Chứng khoán ACB) | vietstock + 24hmoney | 2026-08-29 | two-source agreement |
| underlying | VPB | both | 2026-08-29 | " |
| exercise price | 28,500 VND | both | 2026-08-29 | " |
| exercise ratio | 2:1 (initial **and** adjusted — unchanged) | vietstock | 2026-08-29 | " |
| maturity | 2027-02-17 | both | 2026-08-29 | " |
| last trading | 2027-02-15 | both | 2026-08-29 | " |
| listed volume | 18,000,000 | both | 2026-08-29 | " |
| issue price | 2,400 VND | vietstock | 2026-08-29 | " |

VPB's only 2026 corporate action (5% cash dividend, ex-date 2026-05-15) **predates** the
warrant's 2026-06-17 issue, so the as-issued terms are the effective terms.
24hMoney breakeven 30.12 = 28.50 + 0.81 × 2 independently confirms the ratio.
Sources: `finance.vietstock.vn/chung-khoan-phai-sinh/CVPB2615/cw-tong-quan.htm`,
`24hmoney.vn/covered-warrant/CVPB2615`.

### CTCB2601 — `CONFLICTING` (held out of the quant gate)

Public sources agree on the **as-issued** terms: issuer ACBS, underlying TCB, strike 37,000
VND, ratio 4:1, maturity 2026-10-26, last trading 2026-10-22, listed volume 19,000,000,
issue price 2,000 VND. But:

1. the prior local snapshot (issuer **KIS**, strike **25,000**, ratio **2:1**, maturity
   **2026-12-10**) was wrong on every quant-critical field — corrected in this pass;
2. TCB paid a 700 VND/share cash dividend (ex-date 2026-05-19) during the warrant's life.
   Vietstock reports an adjusted ratio of **3.9176:1**; 24hMoney still shows **4:1** — the
   corporate-action-adjusted effective terms cannot be pinned to one value;
3. a 60% TCB stock bonus is approved but not yet ex (TCB still ~33,400 VND).

Until one authoritative HOSE/VSD adjustment notice is reconciled, CTCB2601 stays
`CONFLICTING` and the quant panel shows "unavailable — conflicting metadata", not a guess.
Sources: `finance.vietstock.vn/chung-khoan-phai-sinh/CTCB2601/cw-tong-quan.htm`,
`24hmoney.vn/covered-warrant/CTCB2601`, VSD dividend notice.
