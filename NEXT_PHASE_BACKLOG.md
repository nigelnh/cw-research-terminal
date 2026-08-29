# CW Research Terminal — Next-Phase Backlog

Created from the Step 12 engineering & recruiter-readiness audit. Items here are **not**
implemented in Step 12 (except the four narrow fixes noted in the audit report). This
backlog drives the next work phase.

**Effort key:** S ≈ ≤half a day · M ≈ 1–3 days · L ≈ 1–2 weeks
**"Changes validated financial semantics?"** — flags anything that alters a number the
quant verification suite pins, so it gets extra review + a fixture update.

Recommended phase order: **P0 → P1 finance → P1 AI → P1 UX setup → P1 UX redesign → P2 → P3.**

---

## P0 — correctness / broken behavior

### P0-1 — Confirm Supabase user tokens are asymmetric (ES256), not legacy HS256
- **Area:** `backend/app/auth/jwt_verifier.py`, Supabase project `ezfcgcfzewtrpevgfzpr`
- **Impact:** If the project still issues HS256 user access tokens, every signed-in
  `/api/me/*` request fails signature verification (backend prod has `SUPABASE_URL` set,
  no `SUPABASE_JWT_SECRET`, so only the JWKS/asymmetric path is active). The public app is
  unaffected; only sign-in breaks.
- **Evidence:** JWKS endpoint serves a single **ES256** key (no HS `kid`), which strongly
  implies asymmetric issuance — but not yet verified with a real user token round-trip.
- **Direction:** During the manual magic-link smoke test, decode the returned
  `access_token` header and confirm `alg` is ES256/RS256. If HS256: enable "JWT signing
  keys → migrate to asymmetric" in the Supabase dashboard (one action), or set
  `SUPABASE_JWT_SECRET` on the backend.
- **Effort:** S · **Deps:** manual sign-in · **Financial semantics:** no

### P0-2 — Monday HOSE live realtime verification
- **Area:** `backend/app/market_data/providers/fiinquant_provider.py`
- **Impact:** Off-session reconnect pacing is fixed & verified, but sustained in-session
  stream stability (trade + BidAsk staying `connected`, no 10 s reconnect loop, quotes /
  bid-ask / analytics advancing, no connection growth over 30–60 min) can only be
  confirmed during a live session.
- **Direction:** Run the 10-point checklist in `DEPLOYMENT_CHECKPOINT.md` on Mon
  2026-08-31 during 09:00–11:30 or 13:00–15:00 ICT.
- **Effort:** S · **Deps:** market hours · **Financial semantics:** no

### P0-3 — STB 1D history is stale (last bar 2026-08-19, ~9 days behind)
- **Area:** production PostgreSQL `market_bars`; startup HV warm-up gap-fill
- **Impact:** STB's HV_22 estimate is computed from a short/stale series. STB is an HV
  underlying only (not in the recruiter demo set), so user-visible impact is low, but any
  quant that leans on STB HV is subtly off.
- **Direction:** one-off `python -m app.persistence.cli backfill --symbols STB --timeframe
  1D --adjusted --from <today-200d>` via `railway ssh`. Root cause is the same 20 s
  warm-up cap that also produced the orphaned runs (now swept) — see P2-2.
- **Effort:** S · **Deps:** none · **Financial semantics:** no (data completeness)

---

## P1 — finance / trading product behavior  *(do NOT implement here — product-polish phase)*

### P1-F1 — `spreadPercent` uses `lastPrice` as denominator (basis mismatch)
- **Area:** `frontend/src/features/market_overview/market_explorer.tsx` (~line 53); also
  wherever spread% is displayed.
- **Impact:** `spread / lastPrice * 100`. Bid/ask are live; `lastPrice` can be a stale
  trade from hours ago (or null → spread% disappears). A live spread measured against a
  stale/absent last is misleading — spread% jumps around for reasons unrelated to the
  actual quote.
- **Direction:** denominate spread% on the **mid** `(bid+ask)/2` when both sides are
  present; show `—` otherwise. Decide one convention and use it in the UI, the AI context
  envelope, and any quant surface consistently.
- **Effort:** S · **Financial semantics:** yes (defines a displayed metric)

### P1-F2 — Moneyness computed twice, inconsistently
- **Area:** `market_explorer.tsx` (AI context: `underlyingPrice / strikePrice * 100`,
  labels ITM/OTM at exactly 100) vs `backend/app/quant/quant_engine.py`
  (`moneyness` + `moneyness_category`, gated on `MetadataVerificationStatus`).
- **Impact:** The AI can be handed a moneyness/label the quant panel refuses to show
  (because CW metadata is `UNVERIFIED`). Two sources of truth for the same concept; the
  frontend one ignores the verification gate and the ATM edge (100% is neither ITM nor
  OTM).
- **Direction:** single source — the backend quant result — surfaced through one field;
  frontend/AI never recompute. Add an explicit `AT_THE_MONEY` band.
- **Effort:** M · **Financial semantics:** yes (classification thresholds)

### P1-F3 — CW warrant metadata is `UNVERIFIED` → no greeks in production
- **Area:** `backend/app/instruments/…` registry, `active_warrants.json`, quant engine
  verification gate.
- **Impact:** `GET /api/quant/CTCB2601` returns `is_available: false`,
  `unavailable_reason: METADATA_NOT_VERIFIED_CURRENT`. The whole quant panel (IV, greeks,
  theo price, moneyness) is empty for the deployed CWs — the headline feature shows
  nothing on the live demo.
- **Direction:** populate + mark-current the `effective_strike` / `effective_ratio` /
  `maturity` / `last_trading_date` for the demo CWs (CTCB2601, CVPB2615) from public HOSE
  listing data; document the verification workflow.
- **Effort:** M · **Financial semantics:** no (unlocks existing, already-validated math)

### P1-F4 — Truthfulness of stale / closed-market / partial states (systematic pass)
- **Area:** all quote-bearing components; `map_snapshot` / `map_patch`; `market_session`.
- **Impact:** The "render `—`, never `0`/`NaN`/stale" contract is asserted in tests, but a
  product pass is needed: is a bid from 11:29 shown as "live" at 11:31 (lunch)? Is a CW
  `Last` from yesterday visually distinct from today's? Is "Market closed" vs "feed
  offline" vs "reconnecting" always correct?
- **Direction:** an explicit freshness/badge system (LIVE / DELAYED / SESSION-CLOSED /
  STALE-<age>) applied uniformly; no realtime number rendered without a freshness marker.
- **Effort:** M · **Financial semantics:** no (presentation), but touches many surfaces

### P1-F5 — Number precision / units review
- **Area:** BSM greeks rounding in `black_scholes.py` (delta 5dp, gamma 8dp, theta/vega/rho
  2dp VND), IV as decimal vs %, VND formatting.
- **Impact:** e.g. theta rounded to 2dp VND can read `0.00` for a low-ratio warrant with
  real daily decay; gamma at 8dp is noise for display. IV shown as `0.325` in some places,
  `32.5%` in others (prompt says decimal; UI may differ).
- **Direction:** define display precision per metric separately from compute precision;
  one IV convention end-to-end; a `formatVnd` / `formatPct` / `formatGreek` helper set.
- **Effort:** S–M · **Financial semantics:** display only (compute unchanged)

### P1-F6 — Expiry / near-maturity edge cases
- **Area:** `black_scholes.py` `T <= 0` path, DTE display, `last_trading_date` vs `maturity`.
- **Impact:** At/after last trading date the CW is intrinsic-only; verify the UI stops
  showing IV/greeks as if tradable, shows DTE correctly (calendar vs trading days), and
  handles `T` between last-trading and maturity.
- **Direction:** an explicit contract-status state machine (ACTIVE → NEAR_EXPIRY →
  LAST_DAY → EXPIRED) driving what analytics render.
- **Effort:** M · **Financial semantics:** yes (behavior near T→0)

---

## P1 — AI research quality  *(do NOT implement here — AI phase)*

### P1-A1 — No causal-claim / correlation-vs-causation guardrail
- **Area:** `backend/app/ai/ai_system_prompt.py`
- **Impact:** Nothing in the prompt stops "the dividend announcement caused HPG to drop
  3%". The assistant has no news/event feed but isn't told so — it can imply knowledge it
  doesn't have.
- **Direction:** add explicit instructions: (a) you have no news/events/fundamentals feed
  — only the market/quant/history context in the blocks; (b) describe co-movement, never
  assert causation; (c) when a question needs event data, say what's missing.
- **Effort:** S · **Financial semantics:** no

### P1-A2 — Prompt promises data the context never carries
- **Area:** `ai_system_prompt.py` (mentions `historicalVolatility`, "recent price action")
  vs `market_explorer.tsx` `contextEnvelope` (no HV, no historical series) and the tool set
  (no historical tool).
- **Impact:** The model is told about HV/history it may never receive → fabrication risk,
  or confident "I don't have that" when it actually could via a missing tool.
- **Direction:** align three things — the envelope schema, the tool registry, and the
  prompt. Add a `get_history` tool (bounded) and include HV in the envelope, or remove the
  prompt references. Tag each context field with provenance (OBSERVED / COMPUTED /
  HISTORICAL).
- **Effort:** M · **Financial semantics:** no

### P1-A3 — Hardcoded / stale symbol recognition in the tool executor
- **Area:** `backend/app/ai/tools/tool_executor.py` — `STOCK_PATTERN` is a fixed 13-ticker
  regex; `PRIMARY_SYMBOLS` still lists the old acceptance universe (`CVHM2615`, `CHPG2541`)
  not the deployed CWs.
- **Impact:** Ask about GAS/PLX/ACB (or any stock outside the 13) → the AI can't fetch its
  quote/analytics. Stale primary set misleads intent resolution.
- **Direction:** resolve symbols against the live `InstrumentRegistry` instead of a regex
  whitelist; drop `PRIMARY_SYMBOLS` or derive it.
- **Effort:** S · **Financial semantics:** no

### P1-A4 — Free model vs prompt ambition
- **Area:** `OPENROUTER_MODEL=minimax/minimax-m3:free`
- **Impact:** A sophisticated provenance-aware financial-reasoning prompt on a weak free
  model → inconsistent instruction-following, especially the "no markdown" and
  "distinguish observed vs computed" rules.
- **Direction:** evaluate 2–3 candidate models for this prompt; keep the cost cap; consider
  a small paid model for the demo if the trial economics allow. Add a lightweight eval
  harness (fixed prompts + rubric).
- **Effort:** M · **Financial semantics:** no

### P1-A5 — Event-aware research workflow (the roadmap feature)
- **Area:** new subsystem — do not start yet.
- **Direction:** market/corporate event → resolve underlying → gather available
  market+history context → evaluate related CWs → quantify (IV/greeks/HV/moneyness) →
  summarize/compare. Any new data must come through the `MarketDataProvider` boundary from
  FiinQuant or another legitimate/public source.
- **Effort:** L · **Financial semantics:** no (compose existing)

---

## P1 — UX / UI  *(do NOT implement here — UX phase; see §UX-SETUP below)*

### P1-U1 — All styling is inline `style={{}}` objects
- **Area:** every component (`instrument_drawer.tsx`, `trading_chart.tsx`, etc.)
- **Impact:** No design-system discipline; hard to theme, ensure contrast, keep spacing/
  type consistent; large diffs for visual tweaks; no hover/focus/media-query support
  without JS.
- **Direction:** adopt a token-driven approach (CSS modules or a small utility layer over
  the existing `--` custom properties). This is the backbone of the UX phase.
- **Effort:** L · **Financial semantics:** no

### P1-U2 — Oversized components
- **Area:** `instrument_drawer.tsx` (864 lines), `trading_chart.tsx` (691),
  `ai_assistant_bubble.tsx` (627)
- **Impact:** weak boundaries, hard to test/iterate on visually.
- **Direction:** decompose into sub-components (header / terms / analytics grid / chart /
  actions) during the redesign.
- **Effort:** M–L · **Financial semantics:** no

### P1-U3 — First-15-seconds clarity
- **Impact:** The landing view drops straight into a dashboard workspace. A recruiter with
  no context doesn't learn what a covered warrant is, what "CW" means, or where the demo
  path is. (README now covers this; the app does not.)
- **Direction:** a lightweight, dismissible intro/empty-state on first visit; a one-line
  "what am I looking at" affordance; a "start here" sample instrument.
- **Effort:** M · **Financial semantics:** no

### P1-U4 — Realtime vs historical distinguishability
- **Impact:** section 3 audit — are live values visually separable from historical? Are
  loading / unavailable / stale / partial states obvious?
- **Direction:** part of the P1-F4 freshness-badge system, plus a consistent skeleton /
  empty / error component set.
- **Effort:** M · **Financial semantics:** no

### P1-U5 — Accessibility gaps (statically visible)
- **Area:** `sign_in_dialog.tsx` (email input has placeholder, no associated `<label>`;
  no focus trap in the modal); general focus-order and contrast pass needed.
- **Impact:** keyboard/AT users; also a credibility signal.
- **Direction:** proper `<label htmlFor>` / `aria-label`, focus trap + return-focus on
  modal close, a contrast pass against the dark palette, `prefers-reduced-motion`.
  (Baseline is already decent: semantic `<button>` everywhere, landmarks, 48 aria attrs.)
- **Effort:** M · **Financial semantics:** no

### P1-U6 — Mobile / small-viewport pass
- **Impact:** `100vw`/`100vh` shell, fixed `maxWidth: 1600`, dense tables — untested on
  narrow viewports.
- **Direction:** responsive audit during the redesign; decide the mobile story (read-only
  summary vs full workspace).
- **Effort:** M · **Financial semantics:** no

---

## P2 — performance

### P2-P1 — Frontend bundle: single 704 KB JS chunk, zero code-splitting
- **Area:** `frontend/` — no `React.lazy`/`Suspense`/dynamic `import()` anywhere.
- **Impact:** every visitor downloads charts (chart.js **and** lightweight-charts — two
  libs), Supabase auth SDK, `date-holidays`, AI UI, upfront.
- **Direction:** route/tab-level `React.lazy` for the research tab, the AI bubble, and the
  chart; lazy `getSupabase()`; pick one charting library.
- **Effort:** M · **Financial semantics:** no

### P2-P2 — Font subsetting
- **Area:** `src/main.tsx` — `@fontsource/inter/{400,500,600,700}.css` +
  `@fontsource/jetbrains-mono/{400,500}.css` pull **all** language subsets (36 woff2,
  ~1.9 MB of assets).
- **Direction:** import `…/latin-400.css` + `…/vietnamese-400.css` only (keep Vietnamese —
  it's a VN market app). Or self-host a subset.
- **Effort:** S · **Financial semantics:** no

### P2-P3 — `/health` is verbose and unauthenticated
- **Area:** `backend/app/main.py` `root_health()`
- **Impact:** No secret leak, but it exposes pool sizes, gate limits, quant-scheduler
  internals, WS caps, provider status to anyone. Fine for a demo; a prod reviewer would
  flag it.
- **Direction:** keep `/healthz` (already minimal) public; trim `/health` to
  status booleans, or gate the detailed block behind a header/token.
- **Effort:** S · **Financial semantics:** no

### P2-P4 — `npm audit`: 3 vulns (1 critical, 1 high, 1 moderate) — all dev-only
- **Area:** `happy-dom` (critical, test-only), `esbuild`<=0.24 via `vite`<=6 (moderate,
  dev-server-only).
- **Impact:** none in production (not in the shipped bundle); bad look if a reviewer runs
  `npm audit`.
- **Direction:** bump `vite` (→ 7/8) and `happy-dom`; both are breaking, so do it as a
  deliberate task with a full build+test pass.
- **Effort:** M · **Financial semantics:** no

### P2-P5 — Node engine mismatch
- **Area:** `@supabase/supabase-js@2.112` requires Node ≥22; local dev on Node 20 warns
  (`EBADENGINE`). README says "Node 18+".
- **Direction:** either pin supabase-js to a Node-20-compatible line or bump the README /
  `.nvmrc` to Node 22 (Vercel prod already builds on 22). Add an `engines` field +
  `.nvmrc`.
- **Effort:** S · **Financial semantics:** no

---

## P2 — engineering cleanup

### P2-2 — HV warm-up cancels in-flight gap-fills (root cause of orphaned runs + STB stale)
- **Area:** `backend/app/quant/historical_volatility_service.py` (the `asyncio.wait_for`
  20 s warm-up) → cancels `execute_gap_fill` coroutines mid-fetch.
- **Impact:** Step 12 added a startup sweep + a `try/finally` that finalizes the run, so
  no more stuck `RUNNING` rows — **but** the underlying fills are still abandoned, leaving
  short series (P0-3). Also produces log noise.
- **Direction:** decouple — let the warm-up return a "not ready yet" HV and let the
  gap-fills complete detached (they already single-flight + advisory-lock), instead of
  cancelling them. Or raise the warm-up budget and make it non-blocking.
- **Effort:** M · **Financial semantics:** no

### P2-3 — CI (there is none)
- **Area:** repo — no `.github/workflows/`.
- **Impact:** A portfolio repo claiming ~1100 tests with no green CI badge is a visible
  gap; also no guard against regressions on push.
- **Direction:** one workflow: `pytest -q` + `pyright app` + (frontend) `vitest run` +
  `tsc --noEmit` + `npm run build`. The backend suite needs no secrets (all mocked; PG
  tests skip without `initdb`, or add a `postgres` service container). Add the status
  badge to the README.
- **Effort:** S–M · **Financial semantics:** no

### P2-4 — `audit/` directory is orphaned scaffolding
- **Area:** `audit/` — 9 files, referenced by nothing (no CI, no package.json, no README).
  - `black_scholes_verification.py` — genuine independent-cross-check evidence → **MOVE**
    into `backend/tests/` as a real pytest (or `verification/` with a README).
  - `test_research_platform.ts`, `live_frontend_acceptance_test.ts`,
    `live_market_acceptance_runner.py`, `test_live_quant_integration.py` — superseded by
    vitest/pytest; a `test_`-prefixed file no runner executes is **actively misleading** →
    **DELETE** (or move to `verification/` and rename without the `test_` prefix).
  - `benchmark_*.js` (3) — orphaned micro-benchmarks → **MOVE** to `benchmarks/` + README,
    or **DELETE**.
- **Direction:** consolidate into one clearly-labeled `verification/` folder with a README
  explaining what each script proves, or fold the valuable ones into the test tree.
- **Effort:** S · **Financial semantics:** no

### P2-5 — `docs/` is gitignored but load-bearing references point into it
- **Area:** `.gitignore:93` (`docs/`); code cites `docs/domain/warrant_domain_contract.md`,
  `docs/domain/historical_formula_catalog.md`, `docs/data_dictionary/warrant_info_columns.md`
  (e.g. `dividend_convention.py` cites `warrant_domain_contract.md §3`). None exist in the
  canonical repo — the originals live only in the private `hq_gui` working dir.
- **Impact:** A reviewer following the citations in the (excellent) design comments hits
  nothing. Weakens the "defend the design" story.
- **Direction:** un-ignore `docs/`; author 3 concise, public-facts-only domain docs
  (CW contract mechanics; HV/quant formula catalog; warrant-info column dictionary) —
  independently written, no proprietary content. The formula catalog can absorb the
  worthwhile parts of `progress.md`.
- **Effort:** M (content-heavy — pairs well with the finance phase) · **Financial
  semantics:** documents them, doesn't change them

### P2-6 — `progress.md` (25 KB, tracked) is a stale internal changelog
- **Area:** repo root.
- **Impact:** References the private repo's commit hashes (`c0fff65:server/…`), legacy
  desk spreadsheets, stale counts ("42/42 tests" — now 903), a "Next Steps" TODO dump.
  Recruiter-facing clutter that contradicts the current state.
- **Direction:** **DELETE** from the repo (git history is the real changelog); migrate the
  genuinely useful formula-lineage table into `docs/domain/historical_formula_catalog.md`
  (P2-5).
- **Effort:** S · **Financial semantics:** no

### P2-7 — `DEPLOYMENT_CHECKPOINT.md` (23 KB, tracked) is session ops notes
- **Area:** repo root.
- **Impact:** Detailed Step-11 operational log + Monday checklist. Useful *now*; not
  recruiter-facing long-term.
- **Direction:** after P0-1/P0-2 close, delete it or move to a gitignored `docs/internal/`.
  Keep `DEPLOYMENT.md` (the clean doc).
- **Effort:** S · **Financial semantics:** no

### P2-8 — `backend/poc/fiinquant/` (8 files, tracked)
- **Area:** SDK reverse-engineering probes (own `requirements.txt`, `.env.example`).
- **Impact:** Decent engineering evidence (methodical mapping of an undocumented SDK) but
  `poc/` naming reads as unfinished; excluded from the Docker image already.
- **Direction:** **MOVE** to `docs/exploration/fiinquant-sdk/` with a short README framing
  it as "how the vendor SDK was mapped", or **KEEP** with a top-level README note.
- **Effort:** S · **Financial semantics:** no

### P2-9 — `test_research_platform.ts` rename (asked explicitly)
- Covered by P2-4: don't just rename — the file is a hand-rolled `assert()` harness that
  vitest supersedes and no runner executes. **DELETE** it, or if any assertion isn't
  covered by vitest, port that case into `frontend/src/__tests__/` and delete the file.
- **Effort:** S · **Financial semantics:** no

### P2-10 — `.DS_Store` at repo root
- Not tracked (gitignored), but present on disk. Confirm `.gitignore` covers `**/.DS_Store`.
- **Effort:** S · **Financial semantics:** no

---

## P3 — future features

- **P3-1** Saved research / notes / backtests (roadmap).
- **P3-2** Google OAuth (currently gated off via `VITE_AUTH_GOOGLE_ENABLED`; needs a Google
  provider configured in Supabase + consent screen).
- **P3-3** Scheduled incremental ingestion (`ingest-cron` service — image + cron start
  command already designed in `DEPLOYMENT.md §7`, deliberately not deployed).
- **P3-4** Multi-instrument compare view; historical IV surface / term structure.
- **P3-5** Alerting (price / IV / DTE thresholds).
- **P3-6** Provider #2 behind `MarketDataProvider` (proves the abstraction).

---

## UX-SETUP — Claude Code tooling for the UX/UI phase

See the audit report §16 for the full ESSENTIAL / USEFUL / UNNECESSARY breakdown and the
staged install plan. Summary:

- **ESSENTIAL:** Playwright (screenshot + interaction on the real app) · the `dataviz` /
  `artifact-design` skills already available · a screenshots-in-repo convention.
- **USEFUL:** an axe-core / accessibility check step · a visual-diff workflow (Playwright
  `toHaveScreenshot`) · a component inventory doc.
- **UNNECESSARY (for now):** Figma MCP (no Figma in use) · Mobbin automation · heavy
  design-system frameworks · browser-devtools MCP.
