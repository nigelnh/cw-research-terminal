# Step 11 Deployment — Checkpoint

_Last updated: 2026-08-28 (session resume). No secrets in this file._

## Progress this session
- Supabase MCP connected (project `ezfcgcfzewtrpevgfzpr`, scoped `development,docs`). ✅
- Retrieved via MCP: Project URL `https://ezfcgcfzewtrpevgfzpr.supabase.co`; publishable key
  `sb_publishable_...` (client-safe). JWKS endpoint serves an **ES256** key → backend
  asymmetric JWT verification will work (no `SUPABASE_JWT_SECRET` needed). ✅
- Supabase auth settings (`GET /auth/v1/settings`): `email: true` (magic link zero-config),
  **`google: false`** — Google OAuth provider is NOT configured; the UI "Sign in with Google"
  button will fail until a Google provider is added in the Supabase dashboard. Email magic
  link works once redirect URLs are set.
- Vercel env (Production + Preview): `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` set. ✅
- Railway `backend` `SUPABASE_URL`: **NOT set** — `railway variables --set` is blocked by the
  Claude Code auto-approve classifier. Needs the user to run it or approve.
- Redirect-URL research (docs): separators are `.` and `/`; `*` matches a non-separator run.
  App always redirects to `window.location.href` = origin + path `/` + optional query
  (`?tab`,`?symbol`,`?range`,`?interval`,`?code`), never a deeper path. → narrowest pattern:
  **`https://cw-research-terminal.vercel.app/*`** (fallback `/**` if any redirect is rejected).
- Railway incident (deploy backlog) appears resolved (~Aug 17–20); control-plane API responsive.
- Still pending: manual Supabase dashboard URL config (A.6), frontend prod redeploy (A.7),
  all of Part B (recreate Postgres/Redis, deploy backend), Part C smoke tests.

_Original checkpoint below._

---

_Prior last-updated: 2026-08-29 ~02:55 UTC._

Canonical repo: `~/Developer/cw-research-terminal` · deploys from `github.com/nigelnh/cw-research-terminal` (`main`).
Constraint: **$0 out-of-pocket** — Railway Free Trial only, no Hobby upgrade, no card.

---

## Current state

### Vercel (frontend) — ✅ LIVE
- Production URL: **https://cw-research-terminal.vercel.app** (HTTP 200)
- Project: `nigelnhs-projects/cw-research-terminal` (`prj_D0zAwTrwQiUCuRj3FLBLmYd1CAIz`)
- Root dir `frontend/`, framework Vite, connected to GitHub `main` for push-deploys
- Env vars set (Production + Preview): `VITE_DATA_MODE=live`, `VITE_MARKET_DATA_REST_URL`,
  `VITE_MARKET_DATA_WS_URL`, `VITE_DEFAULT_LIVE_SYMBOLS=VNINDEX`, `VITE_MAX_REALTIME_SYMBOLS=33`
- **Not yet set:** `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (anonymous core until wired)
- Current build = anonymous-only (no "Sign in" button — needs the two Supabase vars + rebuild)

### Railway (backend + DB) — ⚠️ BLOCKED by provider incident
- Project: `cw-research-terminal` (`46188230-5422-456a-ba08-3e72c7b2e91d`), env `production`
- Active Railway incident: "Deployments slow to start" (deploy-worker backlog). Deploys stalled
  30–45 min; control-plane API calls timing out.
- **`backend` service** — exists, fully configured, **NOT deployed** (`deploy=NONE`). Domain
  reserved: `https://backend-production-f1b1.up.railway.app`
- **`Postgres` and `Redis` services — GONE.** Created earlier, got stuck in the incident, then
  removed (delete calls that had timed out eventually processed). Must be re-created.
- Region: leave as Railway default this time — do **not** set region via API (that tangled the
  first attempt). Co-locate all services in whatever region `backend` lands in.

#### backend service — env vars already set (names only)
```
ENVIRONMENT=production           CLIENT_IP_TRUST_MODE=railway
PUBLIC_RATE_LIMIT_ENABLED=true   RATE_LIMIT_BACKEND=redis
REDIS_ENABLED=true               REDIS_URL=${{Redis.REDIS_URL}}          <- ref, currently dangling
DATABASE_ENABLED=true            DATABASE_URL=${{Postgres.DATABASE_URL}} <- ref, currently dangling
DATABASE_REQUIRE_ON_STARTUP=true HISTORY_SOURCE_MODE=auto
PUBLIC_REALTIME_ENABLED=true     SECURITY_HEADERS_ENABLED=true
SECURITY_HSTS_ENABLED=false      (flip true only after HTTPS verified end-to-end)
AI_ENABLED=true                  AI_PUBLIC_ENABLED=true
OPENROUTER_MODEL=minimax/minimax-m3:free   AI_DAILY_REQUEST_BUDGET=200
OPENROUTER_SITE_URL / OPENROUTER_APP_NAME
FIINQUANT_ENABLED=true
CORS_ALLOWED_ORIGINS=https://cw-research-terminal.vercel.app
ALLOWED_HOSTS=backend-production-f1b1.up.railway.app
RAILWAY_DEPLOYMENT_DRAINING_SECONDS=30
FIINQUANT_USERNAME / FIINQUANT_PASSWORD / OPENROUTER_API_KEY   <- secrets, set via stdin, not echoed
```
- **Not yet set:** `SUPABASE_URL` (needed for auth on `/api/me/*`)
- The two `${{Postgres.*}}` / `${{Redis.*}}` refs will resolve again only if the recreated
  services are named **exactly** `Postgres` and `Redis`.

### Supabase (Auth only — Railway PG stays the app DB) — ⚠️ MCP pending approval
- Target project: `ezfcgcfzewtrpevgfzpr`
- `.mcp.json` added to canonical repo (project scope). Clean: no tokens; `project_ref=ezfcgcfzewtrpevgfzpr`;
  `features=development,docs` only. **Not committed. Not in the old hq_gui repo.**
- MCP status: `⏸ Pending approval` — needs interactive approve + Supabase OAuth.

#### Frontend auth implementation (inspected — facts for the Supabase dashboard step)
- Env vars the code reads: `VITE_SUPABASE_URL`, **`VITE_SUPABASE_ANON_KEY`** (only in
  `src/data/auth/supabase_client.ts`). Flow: PKCE, `detectSessionInUrl`.
- Redirect target: **`window.location.href`** for both Google OAuth (`redirectTo`) and email
  magic link (`emailRedirectTo`). App is a single-page app served at `/` (Vercel SPA rewrite);
  URL may carry research query state (`?tab`, `?symbol`, `?range`, `?interval`), scrubbed after
  callback. **No dedicated `/auth/callback` route.**
- Sign-in methods in the UI: Google OAuth (needs a Google provider configured in Supabase) +
  email magic link (zero-config via Supabase built-in email).

---

## Exact next actions

### A. Supabase wiring (do now — Railway-independent)
1. **You:** run `/mcp` in Claude Code → approve `supabase` server → `Authenticate` → complete
   Supabase OAuth **for project `ezfcgcfzewtrpevgfzpr` only**.
2. Verify MCP is scoped to that one project.
3. Via MCP `development` tools: get **Project URL** and **publishable (anon) key**. Do NOT
   fetch any service-role/secret key.
4. Set (never commit):
   - Railway `backend`: `SUPABASE_URL=<project url>`
   - Vercel (Production + Preview): `VITE_SUPABASE_URL=<project url>`,
     `VITE_SUPABASE_ANON_KEY=<publishable key>`
5. Check the current Supabase redirect-URL matching rules via MCP `docs`; pick the **narrowest**
   pattern that covers `https://cw-research-terminal.vercel.app/` plus preserved query state.
6. **Manual dashboard step (MCP can't set Auth URLs):** Supabase → Authentication → URL
   Configuration:
   - Site URL: `https://cw-research-terminal.vercel.app`
   - Redirect URLs: the narrow pattern from step 5 (candidate: `https://cw-research-terminal.vercel.app/**`;
     confirm against docs first). No preview-domain wildcards.
7. `vercel deploy --prod` (rebuild frontend with the Supabase vars) — "Sign in" appears.

### B. Railway (when the incident clears — recheck `https://status.railway.com`)
1. `cd ~/Developer/cw-research-terminal`
2. `railway add --database postgres` then `railway add --database redis` (names must be
   `Postgres` / `Redis`). **Do not touch region via API.**
3. Wait for both to reach a running instance (`scratchpad/rwfull.sh` helper).
4. `railway up --service backend` (or trigger a GitHub deploy) — builds `backend/Dockerfile`.
5. Watch logs: expect `alembic upgrade head` → `0002` → `Application startup complete`.
6. `curl https://backend-production-f1b1.up.railway.app/healthz` → `{"status":"ok"}`
7. `curl .../health` → confirm `production_config_problems: 0`, `database_wired: true`,
   `redis_connected: true`, `client_ip_trust_mode: "railway"`, `market_upstream_status` healthy.
8. DB bootstrap (script drafted at `scratchpad/bootstrap.sh`):
   - `railway run --service backend python -m app.persistence.cli seed-instruments`
   - `railway run --service backend python -m app.persistence.cli backfill --symbols HPG,NVL,VHM,TCB,VPB --timeframe 1D --adjusted --from 2025-09-15`
   - `railway run --service backend python -m app.persistence.cli backfill --symbols CTCB2601,CVPB2615 --timeframe 1D --raw --from 2025-09-15`
   - `... cli status ...` to record instruments/bars/date coverage
9. Flip `SECURITY_HSTS_ENABLED=true` once HTTPS is confirmed end-to-end.

### C. Production smoke tests (after backend is up)
Frontend HTTPS · backend `/health` · WSS `/ws/market` (subscribe, quotes, analytics patches,
one server-side provider shared across tabs, symbol-cap error, counter decrement on disconnect)
· history PostgreSQL-first (DB hit = 0 provider calls; one in-horizon gap = one fill then
DB-only; out-of-entitlement = truthful partial) · quant sample vs local fixtures · rate-limit
429 + Retry-After · body-size 413 · CORS (only the Vercel origin) · TrustedHost · client-IP
spoof resistance (fake XFF/X-Real-IP) · anonymous core fully usable · Supabase sign-in →
watchlist import → refresh persists → sign-out restores anon · AI on (free model) or clean 503.

### D. After 48–72 h
`railway metrics` per service → report actual daily burn (backend / Postgres / Redis) → decide
if Hobby (~$10–15/mo) is worth it. Trial credit ≈ $5, ~12–16 days; then services stop, no charge.

---

## Uncommitted / pending
- `.mcp.json` (commit only after MCP verified: no creds, project-scoped, `development,docs` only)
- `frontend/.gitignore` (added by `vercel link`: `.vercel`, `.env*` — safe to commit)
- Code on `main` is current (`7661390`). `backend/Dockerfile`, `entrypoint.sh`, `railway.json`,
  `vercel.json`, `/healthz`, `CLIENT_IP_TRUST_MODE`, `async_database_url()` all pushed.

## Do NOT
Upgrade Railway to Hobby · add a payment method · set a spending cap · commit any secret /
env value · fetch a Supabase service-role key · enable MCP `database`/`functions`/`storage`/
`branching` · set Railway region via API · run an uncontrolled full-universe backfill.
