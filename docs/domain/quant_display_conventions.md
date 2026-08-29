# Quant display conventions

One definition per user-facing quantity, shared by the UI and the AI research context.
Independently written; generic financial mathematics only.

## Spread and spread %

Single source of truth: `frontend/src/domain/quant_display.ts::computeSpread`.

```
spread      = ask - bid                    (raw VND)
mid         = (bid + ask) / 2
spreadPct   = 100 * spread / mid           (%)
```

Returns **null → renders "—"** unless `bid > 0`, `ask > 0`, `ask >= bid`, `mid > 0`. A
crossed or one-sided quote is never coerced into a number. `lastPrice` is **not** used as a
denominator — it can be a stale trade from hours ago while bid/ask are live.

## Moneyness

Canonical from the backend quant engine (`app/quant/quant_engine.py`). The client **never**
derives `S/K`.

```
moneyness            = round(S / K, 5)              raw numeric ratio (S = underlying spot, K = effective strike)
moneyness_category   = ITM  if S/K > 1 + band
                       OTM  if S/K < 1 - band
                       ATM  otherwise                band = QUANT_MONEYNESS_ATM_BAND (default 0.03)
```

The band is a **label convention only** — the numeric ratio is always reported unbanded,
and the band never enters the Black-Scholes computation. The band edges are inclusive
(exactly ±3% is ATM). If the quant gate rejected the contract's metadata, both `moneyness`
and `moneyness_category` are null and the UI shows "—".

## Units and precision

| Quantity | Stored / computed | API | Display | Display precision |
|---|---|---|---|---|
| Underlying price S | raw VND | raw VND | VND, grouped | 0 dp |
| CW price | raw VND | raw VND | VND, grouped | 0 dp |
| Theoretical price | raw VND per warrant | raw VND | VND, grouped | 0 dp |
| Strike K | raw VND | raw VND | VND, grouped | 0 dp |
| Exercise ratio | e.g. `4.0` (4 warrants : 1 share) | same | `4:1` | — |
| Implied vol (bid/trade/ask/mid) | annualised **decimal** (`0.215`) | decimal | **percent** (`21.5%`) | 1 dp |
| Historical vol (HV₂₂) | annualised decimal, 22 trading sessions | decimal | percent | 1 dp |
| Moneyness ratio | `S/K` decimal | decimal | 3 dp + category | 3 dp |
| Spread | raw VND | raw VND | VND | 0 dp |
| Spread % | — | — | percent | 2 dp |
| DTE | calendar days to **maturity** | int | `Nd` | 0 dp |
| Delta (Δ) | change in CW VND per +1 VND underlying, ÷ ratio | same | number | 4 dp |
| Gamma (Γ) | change in Δ per +1 VND underlying, ÷ ratio | same | number | exponential (2 sig) |
| Theta (Θ) | CW VND per **calendar day** (annual ÷ 365 ÷ ratio) | same | `… ₫` | 2 dp |
| Vega (ν) | CW VND per **+1 volatility point** (+0.01), ÷ ratio | same | `… ₫` | 2 dp |
| Rho (ρ) | CW VND per **+1 rate point** (+0.01), ÷ ratio | same | `… ₫` | 2 dp |

- **IV / HV are decimals internally and percentages on screen.** `0.215 → "21.5%"`.
- **Theta is per calendar day** (ACT/365), not per year.
- **Vega is per +1 vol point (0.01)**, i.e. a +1% absolute move in σ.
- **Gamma** is a tiny per-VND number; it is shown in exponential form rather than with a
  misleading pile of zeros.
- Values are **never rounded before the Black-Scholes computation** — precision above is
  display only.

## DTE vs last trading date

`days_to_expiry` (backend) and the "DTE" row (UI) both count calendar days to the
**maturity** date. The **last trading date** (≈ 2 sessions earlier) is shown as its own
row and drives `contract_state`; after it, the warrant is not tradable.

## Contract lifecycle state

`app/quant/quant_engine.py::derive_contract_state`, from `last_trading_date` /
`maturity_date` / today (VN):

| State | Condition | Tradable? |
|---|---|---|
| `ACTIVE` | > `QUANT_NEAR_EXPIRY_DAYS` (10) before last trading | yes |
| `NEAR_EXPIRY` | within 10 days of last trading | yes |
| `LAST_TRADING_DAY` | today = last trading date | yes |
| `PENDING_MATURITY` | past last trading, ≤ maturity | **no** |
| `EXPIRED` | past maturity | **no** |
| `UNKNOWN` | dates missing | no |

When not tradable, the engine returns `is_available = false`,
`unavailable_reason = "NOT_TRADABLE (…)"`, and clears IV/Greeks — intrinsic value may still
be mathematically defined, but the product must not present a non-tradable contract as if
it has live tradable analytics.

## Freshness / market-session state

The realtime layer already gates wire fields on `display_eligible`
(`app/market_data/market_schemas.py`): outside an active HOSE session bid/ask/last serialise
as `null` and the UI renders "—" rather than a stale value. `market_session` /
`market_session_active` in `/health` and the AI envelope distinguish
`MORNING_SESSION` / `LUNCH_BREAK` / `AFTERNOON_SESSION` / `CLOSED_PRE_OPEN` /
`CLOSED_POST_MARKET` / `CLOSED_WEEKEND`. "Market closed" and "feed offline / reconnecting"
are separate states and must not be conflated. Historical charts remain valid at all times.
A first-class per-value freshness badge (LIVE / DELAYED / SESSION-CLOSED / STALE-<age>) is
tracked in the UX backlog (P1-U4).
