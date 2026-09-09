# CW Research Terminal

**CW Research Terminal is a research workstation for Vietnamese covered warrants and their
underlying equities, combining realtime market monitoring, quantitative analytics,
historical research, and AI-assisted analysis.**

**▶ Live demo: https://cw-research-terminal.vercel.app** — no account needed; the dashboard,
research, market data, quant analytics, and history are all fully public.

It is a personal project. Runtime market data comes from public Vnstock Community
KBS/VCI adapters plus the SSI iBoard WebSocket protocol documented by `vnstock-js`. It is
not affiliated with, sponsored by, or operated on behalf of those projects or providers.

### What is a covered warrant?

A **covered warrant (CW)** is an exchange-listed option-like security issued by a securities
firm. A HOSE call CW gives the holder the right to buy a fixed *underlying* stock (e.g. HPG)
at a fixed *exercise price* by a fixed *maturity*, converted at a fixed *ratio* (e.g. 5:1 —
five warrants per share). Its price is driven by the underlying's price, time to maturity,
and volatility — so it is priced and risk-managed with a Black-Scholes-Merton model. This
terminal pairs each CW with its underlying and computes the standard analytics (theoretical
price, implied volatility, Greeks, moneyness, spread, days-to-expiry).

## What it does

- **Realtime market monitoring** — live bid/ask/trade for a watchlist of covered warrants
  and their underlyings, with normalized state, session-freshness protection, and warm-cache
  recovery.
- **Covered-warrant ↔ underlying comparison** — side-by-side price/return context.
- **Historical market research** — PostgreSQL-first historical bars with charting.
- **Quantitative analytics** — Black-Scholes-Merton theoretical price, implied volatility
  (bid/ask/trade/mid), analytical Greeks, HV_22 historical volatility, moneyness, spread,
  days-to-expiry.
- **AI-assisted analysis** — an assistant that summarizes, explains, and compares the
  current market/quant/history context (OpenRouter; optional).
- **Optional accounts** — Supabase Auth for a per-user server-persisted watchlist. The
  dashboard, research, market data, quant, and history are all fully public without an
  account.

## Architecture (implemented)

```
REALTIME
  SSI iBoard WebSocket + KBS recovery poll  ─►  VnstockProvider
      ─►  MarketState (normalized bid/ask/trade)
      ─►  Redis warm cache (L2 recovery)  ─►  FastAPI WebSocket (/ws/market)  ─►  React
  LiveQuantEngine  ◄─ market ticks  ─►  BSM / IV / Greeks / theo price  ─►  analytics patches ─► WS

HISTORICAL
  history_read_service (PostgreSQL-first)
      complete DB hit          → 0 provider calls
      legitimate in-horizon gap → 1 controlled, single-flighted Vnstock fill → persist
  PostgresHistoricalBarSource → HistoricalVolatilityService (HV_22) → in-memory estimate → LiveQuantEngine

QUANT
  market quote + contract terms (effective strike/ratio)  ─►  BSM / IV / Greeks / theo / HV  ─►  analytics

RESEARCH
  market + history + quant context  ─►  research views  ─►  AI-assisted explanation / comparison / summarization

AUTH (optional)
  Supabase Auth  ─►  JWT verified locally  ─►  /api/me/* only (user-specific persistence)
```

- **`MarketDataProvider`** is a vendor-neutral abstraction (`connect`, `set_subscriptions`,
  `get_historical_bars`, `set_event_callback`). The runtime implementation is
  `VnstockProvider`; source changes stay behind this boundary and do not alter the
  subscription planner, market-state pipeline, or quant engine.
- **Quant math is an independent implementation** of public Black-Scholes-Merton pricing,
  implied-volatility inversion, analytical Greeks, and the HV_22 window. HOSE covered
  warrants are dividend-protected (the issuer adjusts strike/ratio on the ex-date), so the
  analytics engine pins the BSM dividend yield `q = 0` — see
  `backend/app/quant/dividend_convention.py`.

### Design decisions

| Decision | Why |
|---|---|
| `MarketDataProvider` abstraction | Vendor-neutral seam; the subscription planner, market-state pipeline and quant engine never import a vendor SDK. |
| One backend replica / one Uvicorn worker | The provider owns one SSI socket, the bounded recovery poller, and shared in-memory state; a second worker would duplicate upstream traffic and split process-local WS state. |
| PostgreSQL-first history | A complete DB hit makes **zero** provider calls; only a legitimate in-horizon gap triggers **one** controlled, advisory-locked, single-flighted fill, which is then persisted. |
| Redis warm state | L2 recovery of the latest canonical market snapshot across restarts/sessions, plus the distributed rate limiter (separate key prefixes). |
| `q = 0` dividend convention | CWs are dividend-protected via strike/ratio adjustment; a BSM `q > 0` would double-count and underprice. |
| Adjusted stock history vs **RAW** CW history | Underlying HV is computed from corporate-action-adjusted closes (removes ex-date jumps from the volatility estimate); CW bars are stored RAW because CW terms are re-based on the ex-date, so there is nothing to adjust. |

## Testing

Backend **1,500+** pytest cases (quant verification, provider lifecycle, ingestion /
history, auth, rate-limit / security, repo-hygiene) + frontend **~190** vitest cases,
`tsc --noEmit`, and `pyright`. Normal CI tests use captured provider fixtures and make no
live market-data request.

```bash
cd backend && .venv/bin/python -m pytest -q
cd frontend && npm test && npx tsc --noEmit && npm run build
```

The persistence tests spin up a disposable local PostgreSQL cluster and skip cleanly when
`initdb` / `pg_ctl` are not on `PATH`.

## Production hosting

| Piece | Where |
|---|---|
| Frontend (static Vite build) | Vercel — https://cw-research-terminal.vercel.app |
| Backend (FastAPI, 1 replica / 1 Uvicorn worker) | Railway |
| PostgreSQL + Redis | Railway (private networking) |

## Known limitations

- **Single backend replica by design.** The SSI socket, HTTP poller, and in-memory market
  state are process-owned; horizontal scaling would require extracting the provider into its
  own single-instance service with a fan-out bus (see *Design decisions*).
- **Realtime is live only during HOSE hours** (Mon–Fri, 09:00–15:00 ICT, excluding lunch).
  Outside the session the provider closes/pauses the push channel on a session-aware
  cadence and quotes render as `—` rather than stale values.
- **Public upstreams have no exchange-grade SLA.** The KBS recovery path remains active if
  the SSI channel is unavailable, and health reports push and polling evidence separately.
- **AI assistant runs on a free model** and is deliberately cost-capped (daily budget,
  concurrency gate, per-hour rate limit). It summarizes the on-screen market/quant/history
  context; it has no news/event feed.
- No scheduled incremental ingestion yet — history is backfilled explicitly via the CLI.

## Roadmap (not yet implemented)

- **Event-aware research.** Given a market/corporate event: identify the relevant
  underlying → compare pre/post-event market behavior → evaluate the related covered
  warrants using the quantitative context above (price, IV, Greeks, moneyness, spread,
  DTE, HV) → have the AI assistant summarize, compare, and explain.
  Any additional data this requires would be obtained through the existing
  `MarketDataProvider` boundary or the existing persisted public enrichment pipeline.
- Saved research / backtests.

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13, FastAPI, SQLAlchemy 2 (async), Alembic |
| Realtime provider | SSI iBoard WebSocket (documented by `vnstock-js`) + Vnstock KBS recovery polling |
| Storage | PostgreSQL (historical bars), Redis (warm market-state cache + rate limiter) |
| Auth (optional) | Supabase Auth — JWT verified locally; only `/api/me/*` is protected |
| AI assistant (optional) | OpenRouter |
| Frontend | React 18, TypeScript, Vite, TanStack Query |

## Quick start (local)

**Prerequisites:** Python 3.13, Node.js 18+, PostgreSQL 15+, Redis, and a Vnstock Community
API key for the Python data adapter.

```bash
# backend
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env      # fill in VNSTOCK_API_KEY (+ DB/Redis if used)
.venv/bin/alembic upgrade head  # only if DATABASE_ENABLED=true
.venv/bin/python -m app.main    # http://localhost:8501

# frontend
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

## Configuration

All configuration is environment-driven — see **`.env.example`** for the full annotated
list. The only market-data credential the runtime needs is the server-side Vnstock key, and
optionally a PostgreSQL URL, a Redis URL, a Supabase project (auth), and an OpenRouter key
(AI). Never commit a real `.env`.

## Provenance

The domain modeling — covered-warrant contract mechanics, corporate-action term
adjustments, the analytics column set — reflects experience building trading-desk research
tooling during a software-engineering internship. Every line in this repository is an
independent implementation over public market rules and public data sources. The SSI
subscription envelope and frame layout are adapted from the Apache-2.0 `vnstock-js`
project; see `THIRD_PARTY_NOTICES.md`. The repository contains no credentials.
