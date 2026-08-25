import httpx
import json
import math
from datetime import datetime, timezone, timedelta
from app.quant.black_scholes import bs_call_price_share, solve_implied_volatility, check_call_price_bounds
from app.quant.engine import calculate_time_to_maturity

VN_TZ = timezone(timedelta(hours=7))

def audit_live_market():
    r = httpx.get("http://127.0.0.1:8501/api/instruments?active_only=true")
    data = r.json()
    items = data.get("items", [])
    print(f"=== AUDITING {len(items)} ACTIVE INSTRUMENTS ===")

    for it in items:
        sym = it["symbol"]
        u_sym = it["underlying_symbol"]
        K = float(it["strike_price"] or 0)
        CR = float(it["exercise_ratio"] or 1)
        mat = it["maturity_date"]
        issuer = it["issuer"]

        # Fetch live quote for CW and Underlying
        q_resp = httpx.get(f"http://127.0.0.1:8501/api/market/quote/{sym}")
        q_data = q_resp.json() if q_resp.status_code == 200 else {}

        u_resp = httpx.get(f"http://127.0.0.1:8501/api/market/quote/{u_sym}")
        u_data = u_resp.json() if u_resp.status_code == 200 else {}

        b1 = q_data.get("bid1_price")
        a1 = q_data.get("ask1_price")
        lp = q_data.get("last_price")
        S = u_data.get("last_price") or u_data.get("bid1_price")

        T, dte = calculate_time_to_maturity(mat)
        r_rate = 0.05
        q_yield = 0.0

        print(f"\n--- {sym} (Issuer: {issuer}, Underlying: {u_sym}) ---")
        print(f"  Terms: K = {K:,.0f} VND, Ratio = {CR}:1, Maturity = {mat} (T = {T:.5f} yrs, DTE = {dte})")
        print(f"  Live Market: Underlying S = {S}, CW Bid1 = {b1}, Ask1 = {a1}, Last = {lp}")

        if S and S > 0 and K > 0 and T > 0:
            disc_k = math.exp(-r_rate * T)
            lower_share = max(0.0, S - K * disc_k)
            upper_share = S
            lower_cw = lower_share / CR
            upper_cw = upper_share / CR

            print(f"  Theoretical Bounds: [{lower_cw:.2f} VND, {upper_cw:.2f} VND] per CW (Share: [{lower_share:.2f}, {upper_share:.2f}])")

            if b1 is not None and b1 > 0:
                iv_b, r_b = solve_implied_volatility(S, K, T, r_rate, q_yield, b1, exercise_ratio=CR)
                print(f"  IV Bid (from {b1} VND): {iv_b} (Diag: {r_b})")
            if a1 is not None and a1 > 0:
                iv_a, r_a = solve_implied_volatility(S, K, T, r_rate, q_yield, a1, exercise_ratio=CR)
                print(f"  IV Ask (from {a1} VND): {iv_a} (Diag: {r_a})")
            if lp is not None and lp > 0:
                iv_t, r_t = solve_implied_volatility(S, K, T, r_rate, q_yield, lp, exercise_ratio=CR)
                print(f"  IV Trade (from {lp} VND): {iv_t} (Diag: {r_t})")

if __name__ == "__main__":
    audit_live_market()
