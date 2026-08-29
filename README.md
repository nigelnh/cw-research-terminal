# CW Research Terminal

**CW Research Terminal is a research workstation for Vietnamese covered warrants and their
underlying equities, combining realtime market monitoring, quantitative analytics,
historical research, and AI-assisted analysis.**

It is a personal project. Market data is provided by **FiinQuant**. It is not affiliated
with, sponsored by, or operated on behalf of any brokerage.

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
  FiinQuant (SignalR)  ─►  FiinQuantProvider  ─►  MarketState (normalized bid/ask/trade)
      ─►  Redis warm cache (L2 recovery)  ─►  FastAPI WebSocket (/ws/market)  ─►  React
  LiveQuantEngine  ◄─ market ticks  ─►  BSM / IV / Greeks / theo price  ─►  analytics patches ─► WS

HISTORICAL
  history_read_service (PostgreSQL-first)
      complete DB hit          → 0 provider calls
      legitimate in-horizon gap → 1 controlled, single-flighted FiinQuant fill → persist
  PostgresHistoricalBarSource → HistoricalVolatilityService (HV_22) → in-memory estimate → LiveQuantEngine

QUANT
  market quote + contract terms (effective strike/ratio)  ─►  BSM / IV / Greeks / theo / HV  ─►  analytics

RESEARCH
  market + history + quant context  ─►  research views  ─►  AI-assisted explanation / comparison / summarization

AUTH (optional)
  Supabase Auth  ─►  JWT verified locally  ─►  /api/me/* only (user-specific persistence)
```

- **`MarketDataProvider`** is a vendor-neutral abstraction (`connect`, `set_subscriptions`,
  `get_historical_bars`, `set_event_callback`). The only implementation is
  `FiinQuantProvider`; another legitimate provider could be added behind the same boundary
  without touching the subscription planner, market-state pipeline, or quant engine.
- **Quant math is an independent implementation** of public Black-Scholes-Merton pricing,
  implied-volatility inversion, analytical Greeks, and the HV_22 window. HOSE covered
  warrants are dividend-protected (the issuer adjusts strike/ratio on the ex-date), so the
  analytics engine pins the BSM dividend yield `q = 0` — see
  `backend/app/quant/dividend_convention.py`.

## Roadmap (not yet implemented)

- **Event-aware research.** Given a market/corporate event: identify the relevant
  underlying → compare pre/post-event market behavior → evaluate the related covered
  warrants using the quantitative context above (price, IV, Greeks, moneyness, spread,
  DTE, HV) → have the AI assistant summarize, compare, and explain.
  Any additional data this requires would be obtained through the existing
  `MarketDataProvider` boundary from **FiinQuant or another legitimate/public source**.
  The current FiinQuant integration does **not** provide a dedicated event dataset; the
  workflow above is product direction, not shipped functionality.
- Saved research / backtests.

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13, FastAPI, SQLAlchemy 2 (async), Alembic |
| Realtime provider | FiinQuant SignalR |
| Storage | PostgreSQL (historical bars), Redis (warm market-state cache + rate limiter) |
| Auth (optional) | Supabase Auth — JWT verified locally; only `/api/me/*` is protected |
| AI assistant (optional) | OpenRouter |
| Frontend | React 18, TypeScript, Vite, TanStack Query |

## Quick start (local)

**Prerequisites:** Python 3.13, Node.js 18+, PostgreSQL 15+, Redis, and a FiinQuant account
(username / password) for live and historical market data.

```bash
# backend
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env      # fill in FIINQUANT_USERNAME / FIINQUANT_PASSWORD (+ DB/Redis if used)
.venv/bin/alembic upgrade head  # only if DATABASE_ENABLED=true
.venv/bin/python -m app.main    # http://localhost:8501

# frontend
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

## Configuration

All configuration is environment-driven — see **`.env.example`** for the full annotated
list. The only credentials the runtime needs are the FiinQuant account (market data), and
optionally a PostgreSQL URL, a Redis URL, a Supabase project (auth), and an OpenRouter key
(AI). Never commit a real `.env`.

## Tests

```bash
cd backend && .venv/bin/python -m pytest -q
cd frontend && npm test && npx tsc --noEmit && npm run build
```

The persistence tests spin up a disposable local PostgreSQL cluster and skip cleanly when
`initdb`/`pg_ctl` are not on `PATH`. No test makes a real FiinQuant network call.

## Provenance

The domain modeling — covered-warrant contract mechanics, corporate-action term
adjustments, the analytics column set — reflects experience building trading-desk research
tooling during a software-engineering internship. Every line in this repository is an
independent implementation over public market rules and the FiinQuant / public data
sources; it contains no proprietary datasets, endpoints, or credentials.
