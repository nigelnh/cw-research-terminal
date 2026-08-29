"""
Dividend-yield convention for Covered Warrant pricing.

WHY q = 0 (and why this is NOT an incomplete implementation)
-----------------------------------------------------------
HOSE Covered Warrants are **dividend-protected**. When the underlying equity pays a
cash dividend D (or does a stock dividend / bonus / rights issue), the issuer adjusts
the warrant's contract terms on the ex-date (`docs/domain/warrant_domain_contract.md` §3):

    Cash dividend  D :  K_new = K_old - D ,           ratio unchanged
    Stock dividend r :  K_new = K_old / (1 + r) ,     ratio_new = ratio_old / (1 + r)

The strike drop exactly offsets the ex-date drop in the underlying price, so the warrant
holder bears **no dividend drag** - unlike a vanilla listed-equity option holder, who
does (and whose pricing therefore uses a continuous dividend yield q > 0).

Consequences for the model:

1. The Black-Scholes-Merton dividend yield q must be **0.0**. Using q > 0 would model a
   forward reduction (S e^{-qT}) that the strike-adjustment mechanism already neutralises
   - i.e. it would **double-count** the dividend and systematically **underprice** the
   warrant. Representative magnitude (production numbers): a naive q = 3% lowers the
   theoretical CW price by ~4-15% and shifts implied vol by ~70-700 bps.

2. The engine already consumes the corporate-action-**adjusted** `effective_strike` and
   `effective_ratio` from the instrument registry. That is the *only* place dividends
   enter CW valuation. Adding q would be the double-count.

3. Historical volatility is computed from **corporate-action-adjusted** closes. That is
   correct and unrelated: adjusting the return series removes spurious ex-date jumps
   from the *volatility* estimate; it does not touch the *drift* (q).

Evidence (ranked strongest first):
  * VN regulatory framework: the issuer is obliged to adjust CW contract terms (strike,
    conversion ratio) for corporate actions on the ex-date, which removes dividend drag
    for the holder - so a continuous BSM dividend yield q > 0 would double-count.
  * The standard closed-form covered-warrant theoretical price is dividend-free
    Black-Scholes: `theo_prc = C_BS(S, K_effective, T, r, sigma) / conversion_ratio`,
    with no q and no e^{-qT} term.
  * `backend/app/instruments/data/active_warrants.json` - populated `effective_*` terms
    (e.g. CHPG2602 adjusted after an HPG dividend).

The math primitive in `app.quant.black_scholes` keeps a real `q` parameter: it is a
general BSM implementation, it is exercised with q > 0 by the verification suite
(`backend/tests/test_quant_*.py`), and the stateless what-if endpoint
`POST /api/quant/calculate` still accepts an arbitrary `dividendYield`. Only the
canonical CW analytics engine pins q to the convention below.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DividendYieldConvention:
    """The dividend-yield assumption used by the Covered Warrant analytics engine.

    Attributes
    ----------
    value : float
        Annualized **decimal** continuous dividend yield q (0.0 == 0%, never a percent).
    rationale : str
        Why this value is correct for this instrument class.
    source : str
        Where the convention is established in the repository / domain.
    """

    value: float
    rationale: str
    source: str

    def __post_init__(self) -> None:
        # q is an annualized decimal, not a percentage. Guard against a 3.0-means-3% slip.
        if not (0.0 <= self.value < 1.0):
            raise ValueError(
                f"dividend yield convention must be an annualized decimal in [0, 1); got {self.value}"
            )


CW_DIVIDEND_YIELD_CONVENTION = DividendYieldConvention(
    value=0.0,
    rationale=(
        "HOSE covered warrants are dividend-protected: the issuer adjusts the exercise "
        "price (K_new = K_old - D for cash dividends) and, for stock dividends/bonuses, "
        "the conversion ratio, on each ex-date. The holder bears no dividend drag, so a "
        "Black-Scholes dividend yield q > 0 would double-count the protection already "
        "applied through the adjusted strike/ratio and systematically underprice the warrant."
    ),
    source=(
        "VN covered-warrant regulatory framework: issuer corporate-action term adjustments "
        "(strike / conversion ratio on ex-date); standard dividend-free Black-Scholes "
        "closed form for the theoretical price."
    ),
)
