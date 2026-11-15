# CW Research Terminal

A research workstation for Vietnamese covered warrants (CWs) and their underlying stocks:
live quotes, Black-Scholes analytics, price history and an AI research assistant.

**Live demo:** https://cw-research-terminal.vercel.app (no account needed)

A covered warrant is an exchange-listed, option-like security issued by a securities firm.
It gives the right to buy an underlying stock at a fixed strike by a fixed maturity, at a
fixed conversion ratio. The terminal pairs each CW with its underlying and prices it with
Black-Scholes-Merton.

## Features

- **Live watchlist:** bid, ask and last for CWs and their underlyings during HOSE hours.
- **Quant analytics:** theoretical price, implied volatility, Greeks, HV22, moneyness,
  spread and days to expiry.
- **Research:** PostgreSQL-backed price history, charts, news and corporate actions.
- **AI assistant:** explains and compares what is on screen (OpenRouter, optional).
- **Optional sign-in:** Supabase accounts keep a watchlist on the server. Everything else
  is public.

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite (Vercel) |
| Backend | Python 3.13, FastAPI, SQLAlchemy, Alembic (Railway) |
| Storage | PostgreSQL, Redis |
| Market data | Vnstock public adapters, SSI iBoard realtime stream |
| Auth and AI | Supabase Auth, OpenRouter |

## Run locally

You need Python 3.13, Node.js 20+ and a Vnstock API key. PostgreSQL
(`DATABASE_ENABLED=true`) and Redis (`REDIS_ENABLED`) are optional.

```bash
cp .env.example .env                     # set VNSTOCK_API_KEY
cp frontend/.env.example frontend/.env

cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m app.main             # http://localhost:8501

cd ../frontend
npm install && npm run dev               # http://localhost:5173
```

## Test

```bash
cd backend && .venv/bin/python -m pytest -q
cd frontend && npx tsc --noEmit && npm test && npm run build
```

Tests use recorded provider data and make no live market-data calls. The persistence tests
start a throwaway PostgreSQL and skip when `initdb` is not on `PATH`.

## Deployment

The frontend runs on Vercel. The backend, PostgreSQL and Redis run on Railway as a single
backend replica, because that process owns the one realtime market-data connection. See
[DEPLOYMENT.md](DEPLOYMENT.md).

## Notes

- This is a personal project. It is not affiliated with Vnstock, SSI or any other data
  provider, and public data sources have no exchange-grade uptime guarantee.
- Quotes are live only during HOSE trading hours (Mon–Fri, 09:00–15:00 ICT).
- The SSI stream parser is adapted from the Apache-2.0
  [vnstock-js](https://github.com/ttqteo/vnstock-js) project. See
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
