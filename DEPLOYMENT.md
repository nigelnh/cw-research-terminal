# Deployment — CW Research Terminal

Lean, public, recruiter-facing production deployment. The public research product
(dashboard, market data, quant, history, realtime WebSocket) is usable with **no
account**. Supabase Auth is optional and only gates `/api/me/*` (the per-user watchlist).

```
              ┌──────────────┐         ┌────────────────────────────────┐
  browser ──▶ │  Vercel      │  HTTPS  │  Railway                       │
              │  (static     │ ──────▶ │  backend service (FastAPI)     │
              │   Vite SPA)  │  WSS    │    1 replica · 1 uvicorn worker │
              └──────────────┘ ──────▶ │      │            │            │
                                       │      ▼            ▼            │
                                       │  Postgres      Redis          │
                                       │  (private)     (private)      │
                                       └───────┬────────────┬──────────┘
                                               │            │
                              FiinQuant SignalR (1 provider, 2 connections: trade + BidAsk)
                                        OpenRouter (AI, cost-capped)
                                        Supabase Auth (JWKS verify only)
```

## 1. One backend process — non-negotiable

The backend runs **one Railway replica, one container, one Uvicorn worker**
(`entrypoint.sh` → `uvicorn app.main:app --workers 1`).

`FiinQuantProvider` owns persistent SignalR connections and shared in-memory market
state. A second worker or replica would open **duplicate** upstream SignalR connections
against a limited account allowance, duplicate the subscription planner and market-state
cache, and multiply the process-local WS / rate-limit / gate counters.

- Do **not** set `numReplicas > 1` (pinned to 1 in `backend/railway.json`).
- Do **not** switch to Gunicorn multi-worker.
- Horizontal scale would require extracting the provider into its own single-instance
  service with a fan-out bus — explicitly out of scope for this deployment.

## 2. Services

| Service | Platform | Plan | Notes |
|---|---|---|---|
| `frontend` | Vercel | Hobby | static build of `frontend/`, output `dist/` |
| `backend` | Railway | Hobby | Dockerfile `backend/Dockerfile`, 1 replica |
| `Postgres` | Railway | Hobby | private networking, historical bars only |
| `Redis` | Railway | Hobby | private networking, warm cache + rate limiter (separate key prefixes) |
| `ingest-cron` | Railway | Hobby | same image, cron start command, exits after run |

## 3. Backend container

`backend/Dockerfile` — `python:3.13-slim`, deterministic `pip install -r requirements.txt`,
non-root user, no `.env` / secrets / tests in the image. `PORT` from Railway.
`entrypoint.sh`:

1. `alembic upgrade head` (only when `DATABASE_ENABLED=true` and `DATABASE_URL` set) —
   idempotent, safe for a single instance.
2. `exec uvicorn ... --workers 1 --timeout-graceful-shutdown 25 --no-proxy-headers`.

`exec` makes Uvicorn PID 1 so Railway's SIGTERM reaches it directly; the 25 s graceful
window lets the lifespan shutdown close the SignalR connections and drain the analytics
scheduler. Healthcheck: `GET /healthz` (no I/O). Full readiness detail: `GET /health`.

Migrations are **not** run as a Railway "pre-deploy" step — they run in the entrypoint so
there is exactly one migration path and it matches local/dev.

**Historical backfills never run on boot.** Ingestion is always an explicit command
(`python -m app.persistence.cli ...`).

## 4. Client IP / rate limiting behind Railway

`CLIENT_IP_TRUST_MODE=railway`. The client IP is used **only** as a rate-limit key.

- Railway's HTTP edge strips inbound `X-Forwarded-For` and rewrites it so the **left-most**
  entry is the real client. `railway` mode trusts only that entry, and only when
  `ENVIRONMENT=production` **and** a `RAILWAY_*` env marker is present (a client cannot
  set those). It never reads client `X-Real-IP` (unreliable behind Railway's CDN).
- **Deploy the Railway backend service with CDN / edge caching DISABLED.** The above
  contract only holds for the plain HTTP proxy.
- If the environment can't be verified the mode degrades to `direct` (keys on the socket
  peer) rather than trusting a spoofable header.

Residual risk: if Railway changes edge behavior, left-most-XFF could become spoofable →
rate-limit evasion (not an auth/data issue). Compensating controls: AI concurrency gate
(`AI_MAX_CONCURRENT`), optional `AI_DAILY_REQUEST_BUDGET`, an OpenRouter account spend
cap, global WS connection caps, and the `AI_PUBLIC_ENABLED` / `PUBLIC_REALTIME_ENABLED`
kill switches.

## 5. Environment variable matrix

Secrets are set in the Railway/Vercel dashboards, never committed. `DATABASE_URL` /
`REDIS_URL` use Railway **reference variables** (e.g. `${{Postgres.DATABASE_URL}}`).

### backend service (Railway)

| Variable | Secret | Purpose |
|---|---|---|
| `ENVIRONMENT` | no | `production` — activates the production-config guard |
| `PORT` | no | injected by Railway |
| `CORS_ALLOWED_ORIGINS` | no | exact Vercel production origin, e.g. `https://cw-research-terminal.vercel.app` |
| `ALLOWED_HOSTS` | no | exact Railway backend host, e.g. `cw-research-terminal-production.up.railway.app` |
| `SECURITY_HEADERS_ENABLED` | no | `true` |
| `SECURITY_HSTS_ENABLED` | no | `true` **only after** HTTPS verified end-to-end |
| `CLIENT_IP_TRUST_MODE` | no | `railway` |
| `PUBLIC_RATE_LIMIT_ENABLED` | no | `true` |
| `RATE_LIMIT_BACKEND` | no | `redis` |
| `REDIS_ENABLED` | no | `true` |
| `REDIS_URL` | no (ref) | `${{Redis.REDIS_URL}}` (private) |
| `RATE_LIMIT_REDIS_URL` | no (ref) | same as `REDIS_URL` (or leave empty to reuse it) |
| `DATABASE_ENABLED` | no | `true` |
| `DATABASE_URL` | no (ref) | `${{Postgres.DATABASE_URL}}` → app converts to `+asyncpg` |
| `DATABASE_REQUIRE_ON_STARTUP` | no | `true` — refuse to serve without the DB in production |
| `HISTORY_SOURCE_MODE` | no | `auto` (→ postgres_first) |
| `PUBLIC_REALTIME_ENABLED` | no | `true` |
| `FIINQUANT_USERNAME` | **yes** | market data account |
| `FIINQUANT_PASSWORD` | **yes** | market data account |
| `AI_ENABLED` | no | `true` |
| `AI_PUBLIC_ENABLED` | no | `true` if OpenRouter configured + capped, else `false` |
| `OPENROUTER_API_KEY` | **yes** | AI provider key |
| `OPENROUTER_MODEL` | no | default `stealth/ox-alpha` (override as needed) |
| `AI_DAILY_REQUEST_BUDGET` | no | conservative cap for the public demo, e.g. `200` |
| `AI_MAX_OUTPUT_TOKENS` | no | `1024` (default) |
| `SUPABASE_URL` | no | `https://<ref>.supabase.co` (backend verifies JWKS; no secret) |
| `SUPABASE_JWT_AUDIENCE` | no | `authenticated` (default) |
| `ME_WATCHLIST_MAX_ITEMS` | no | `50` (default) |

Must **not** be set in production: `AUTH_TEST_HS256_SECRET`, `ALLOW_SINGLE_PROCESS_RATE_LIMIT`
(Redis limiter is required), `RATE_LIMIT_FAIL_OPEN`.

### ingest-cron service (Railway) — same image

Same DB/Redis/FiinQuant vars as backend. `DATABASE_ENABLED=true`, `DATABASE_URL` ref,
`FIINQUANT_USERNAME` / `FIINQUANT_PASSWORD`. Start command overrides the entrypoint —
see §7.

### frontend project (Vercel)

| Variable | Secret | Purpose |
|---|---|---|
| `VITE_DATA_MODE` | no | `live` |
| `VITE_MARKET_DATA_REST_URL` | no | `https://<backend>.up.railway.app` |
| `VITE_MARKET_DATA_WS_URL` | no | `wss://<backend>.up.railway.app/ws/market` |
| `VITE_DEFAULT_LIVE_SYMBOLS` | no | `VNINDEX` (or the demo set) |
| `VITE_MAX_REALTIME_SYMBOLS` | no | `33` |
| `VITE_SUPABASE_URL` | no | `https://<ref>.supabase.co` |
| `VITE_SUPABASE_ANON_KEY` | no | Supabase **publishable/anon** key (never the service-role key) |

## 6. Database bootstrap (one-time, explicit)

```bash
# 1. migrations run automatically in the backend entrypoint; verify:
railway run --service backend alembic current      # -> 0002 (head)

# 2. seed the public instrument registry into Postgres
railway run --service backend python -m app.persistence.cli seed-instruments

# 3. curated recruiter-demo backfill (serial, in-horizon; NOT the full universe)
#    adjusted daily for stocks + CW underlyings:
railway run --service backend python -m app.persistence.cli backfill \
  --symbols HPG,NVL,VHM,TCB,VPB --timeframe 1D --adjusted --from <today-350d>
#    raw daily for the covered warrants:
railway run --service backend python -m app.persistence.cli backfill \
  --symbols CTCB2601,CVPB2615 --timeframe 1D --raw --from <today-350d>

# 4. verify coverage
railway run --service backend python -m app.persistence.cli status \
  --symbols HPG,NVL,VHM,TCB,VPB --timeframe 1D --adjusted
```

`stock 1D = adjusted`, `CW 1D = raw` — do not mix. FiinQuant horizon ≈ 360 days; keep
each request span ≤ 350 days; requests are serialized by the CLI.

## 7. Incremental ingestion cron

Railway cron service, **same image**, start command:

```
python -m app.persistence.cli incremental --symbols HPG,NVL,VHM,TCB,VPB --timeframe 1D --adjusted \
  && python -m app.persistence.cli incremental --symbols CTCB2601,CVPB2615 --timeframe 1D --raw
```

It uses the historical SDK path only — it never starts the realtime provider — and exits
when done. Overlap window, advisory locking, resumability and the FiinQuant serial-request
policy are all preserved by the CLI.

**Schedule:** the HOSE session closes 15:00 Asia/Ho_Chi_Minh (UTC+7); vendor EOD revisions
settle later. Run **18:00 ICT = 11:00 UTC**, weekdays. Railway cron uses **UTC**:

```
0 11 * * 1-5
```

## 8. Rollback / emergency switches

| Situation | Action |
|---|---|
| Bad frontend deploy | Vercel → Deployments → promote previous production deployment (instant) |
| Bad backend deploy | Railway → backend → Deployments → redeploy previous; or `railway rollback` |
| Bad migration | migrations here are additive; do **not** hand-edit. Restore from a Railway Postgres backup and redeploy the prior image. No destructive migration is part of this release. |
| FiinQuant provider unstable | set `PUBLIC_REALTIME_ENABLED=false` (WS upgrades refused, REST/quant/history unaffected) and redeploy |
| Redis outage | production refuses to start with `RATE_LIMIT_BACKEND=redis` and no Redis (fail-safe). Fix Redis, or temporarily `RATE_LIMIT_BACKEND=memory` + `ALLOW_SINGLE_PROCESS_RATE_LIMIT=true` (single worker → acceptable) and redeploy |
| AI runaway cost | set `AI_PUBLIC_ENABLED=false` (endpoint 503s cleanly, rest of terminal fine); also lower the OpenRouter account cap |
| History gap-fill storming the provider | set `HISTORY_GAPFILL_ENABLED=false` (serves Postgres partials only) |

## 9. Source of truth

All services deploy from **`github.com/nigelnh/cw-research-terminal`** (`main`, the
rewritten clean history). Never from the old `hq_gui` directory, the iCloud working copy,
or the local purge mirror.
