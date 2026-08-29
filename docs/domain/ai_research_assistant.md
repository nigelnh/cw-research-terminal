# AI Research Assistant

The Research Assistant is an embedded chat companion for the CW Research Terminal. It
explains covered-warrant mechanics, summarises the state of an instrument, and compares
what the terminal already shows you. It is a *reading* aid over canonical project data —
not a trading system, a price oracle, or a news service.

This document is a public overview. It deliberately does **not** reproduce the full system
prompt.

## What it can do

| Area | Supported | Notes |
|---|---|---|
| Explain CW concepts (moneyness, IV, Greeks, exercise ratio, DTE, settlement) | Yes | Vietnam market, HOSE, cash-settled European calls |
| Report the current quote / spread / % change for a tracked symbol | Yes | From MarketState; only when the session makes quotes display-eligible |
| Report contract reference terms (issuer, underlying, strike, ratio, maturity) | Yes | From the InstrumentRegistry, with a verification grade |
| Report computed analytics (IV, Greeks, moneyness, theoretical value) | Yes, when the quant gate is open | Requires verified terms + a usable underlying spot |
| Summarise recent end-of-day price action / realised range | Yes, from stored history | `get_history` reads only persisted daily bars; it never fetches on demand |
| Compare instruments on the dashboard / watchlist | Yes | Uses the live tracked universe |
| Say why a price moved (news, earnings, flows, macro) | **No** | There is no news / filings / corporate-action / macro feed |
| Give a price target or a buy / sell recommendation | **No** | It will lay out the setup, risks, missing data, and triggers instead |
| Fabricate a number that is missing from context | **No** | It names the missing input |

## Data provenance

Every figure the assistant states has exactly one origin, and it keeps them distinct:

- **OBSERVED** — a live or warm-cache market value (price, bid/ask, volume, % change).
- **COMPUTED** — produced now by the project quant engine (IV, Greeks, moneyness, theoretical value).
- **HISTORICAL** — persisted end-of-day bars (recent price action, realised volatility).
- **REFERENCE** — static contract terms from the registry, carrying a verification grade.
- **USER** — something you asserted in the conversation; attributed to you, not promoted to fact.
- **UNAVAILABLE** — not in context; stated plainly, with the best adjacent data offered.

## Guardrails

- **No invented causality.** It can describe *what* the data shows (direction, magnitude,
  spread, volatility, time decay); it will not attribute a move to a specific event it was
  not told about.
- **Metadata verification is respected.** Contract terms marked `CONFLICTING` or
  `UNVERIFIED` are not treated as authoritative, and analytics that depend on them are
  reported as unavailable rather than estimated.
- **Language discipline.** The model output is a *theoretical value under stated
  assumptions*, never "the fair value". Implied volatility and historical volatility are
  never equated. Delta is a hedge ratio, not a probability of profit.
- **Prompt-injection resistant.** Application context and pasted text are treated as data;
  instructions embedded in them ("ignore previous instructions", "reveal your prompt") are
  not followed.

## Tools available to the assistant (all read-only, bounded)

`get_market_status`, `get_quote`, `get_order_book`, `get_dashboard_snapshot`,
`get_instrument`, `get_quant`, `get_history`. At most 4 tool calls per turn, results cached
within the turn, strict whitelist. Symbols are validated against the canonical instrument
resolver before any tool runs.

## Cost and availability controls

- Runs on a free OpenRouter model by default.
- Per-process daily request budget, global concurrency gate, HTTP rate-limit tier, bounded
  output tokens, bounded input size.
- When the assistant is disabled or a limit is hit, the UI shows a short message; the
  backend attaches an internal failure code (`X-AI-Error-Code` header / SSE `code` field)
  for diagnosis. Raw provider errors and secrets are never sent to the browser.

## Failure codes

`AI_DISABLED`, `AI_BUDGET_EXCEEDED`, `RATE_LIMITED`, `MODEL_UNAVAILABLE`,
`UPSTREAM_AUTH_ERROR`, `UPSTREAM_TIMEOUT`, `UPSTREAM_RATE_LIMIT`, `UPSTREAM_ERROR`,
`INVALID_REQUEST`, `STREAM_INTERRUPTED`, `NETWORK_ERROR`, `INTERNAL_ERROR`.

## Evaluating changes

`backend/scripts/ai_eval_harness.py` runs a 16-prompt set against a running server and
scores responses on an 8-criterion rubric (fabrication, causality, language, provenance,
plain text, graceful-missing, metadata respect, injection resistance). It only ever
exercises the model the target server is configured with; to compare models, point
`--targets` at 2–3 servers.
