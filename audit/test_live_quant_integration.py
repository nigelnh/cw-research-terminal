"""
Live Quant Analytics Integration Verification Script.
Queries the running FastAPI backend on http://127.0.0.1:8501 for active Covered Warrant quantitative metrics.
"""

import asyncio
import httpx
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LiveQuantVerification")


async def verify_live_quant():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8501", timeout=10.0) as client:
        # 1. Verify /api/quant/calculate endpoint
        logger.info("\n[TEST 1] Testing /api/quant/calculate (Black-Scholes Stateless Solver)...")
        calc_resp = await client.post(
            "/api/quant/calculate",
            json={
                "underlyingPrice": 22100.0,
                "strikePrice": 22000.0,
                "timeToMaturity": 0.24,
                "riskFreeRate": 0.05,
                "dividendYield": 0.0,
                "volatility": 0.35,
                "exerciseRatio": 2.0,
                "marketPrice": 650.0,
            },
        )
        assert calc_resp.status_code == 200, f"Expected 200, got {calc_resp.status_code}"
        calc_data = calc_resp.json()
        logger.info(f"  ✓ Calculate Response: {json.dumps(calc_data, indent=2)}")
        assert calc_data.get("theoreticalPrice") is not None
        assert calc_data.get("delta") is not None
        assert calc_data.get("impliedVolatility") is not None

        # 2. Verify /api/quant/CHPG2602 (Live Warrant Analytics)
        logger.info("\n[TEST 2] Testing /api/quant/CHPG2602 (Live Event-Driven Analytics)...")
        an_resp = await client.get("/api/quant/CHPG2602")
        assert an_resp.status_code == 200, f"Expected 200, got {an_resp.status_code}"
        an_data = an_resp.json()
        logger.info(f"  ✓ CHPG2602 Analytics: {json.dumps(an_data, indent=2)}")
        assert an_data.get("symbol") == "CHPG2602"
        assert an_data.get("underlying_symbol") == "HPG"
        # If market ticks received: is_available is True with calculated moneyness
        # If off-market session before ticks: unavailable_reason is UNDERLYING_SPOT_PRICE_UNAVAILABLE
        if an_data.get("is_available") is True:
            assert an_data.get("moneyness") is not None
            assert an_data.get("moneyness_category") in ("ITM", "ATM", "OTM")
            # Theoretical price decoupled from IV Mid
            assert an_data.get("theoretical_price") is None or isinstance(an_data.get("theoretical_price"), (int, float))
            assert an_data.get("model_price_at_iv_mid") is None or isinstance(an_data.get("model_price_at_iv_mid"), (int, float))
        else:
            assert an_data.get("unavailable_reason") in (
                "UNDERLYING_SPOT_PRICE_UNAVAILABLE",
                "METADATA_NOT_VERIFIED_CURRENT",
            )

        # 3. Verify Data-Quality Guard on Invalid/Partial Warrant
        logger.info("\n[TEST 3] Testing Data-Quality Guard on UNKNOWN/PARTIAL Warrant...")
        part_resp = await client.get("/api/quant/CHPG2401")
        assert part_resp.status_code == 200
        part_data = part_resp.json()
        logger.info(f"  ✓ Expired Warrant Response: {json.dumps(part_data, indent=2)}")
        assert part_data.get("is_available") is False
        assert "LIFECYCLE_NOT_ACTIVE" in str(part_data.get("unavailable_reason")) or "EXPIRED" in str(part_data.get("unavailable_reason"))

        logger.info("\n" + "=" * 70)
        logger.info("  ✓ ALL LIVE QUANT ANALYTICS INTEGRATION CHECKS PASSED")
        logger.info("=" * 70)


if __name__ == "__main__":
    asyncio.run(verify_live_quant())
