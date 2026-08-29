"""Quant adversarial-input hardening (Step 10 sections 7, 26). Formulas unchanged."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)

_OK = {"underlyingPrice": 30000, "strikePrice": 25000, "timeToMaturity": 0.5,
       "riskFreeRate": 0.05, "volatility": 0.30, "exerciseRatio": 2.0}


def test_normal_request_is_unchanged():
    r = client.post("/api/quant/calculate", json=_OK)
    assert r.status_code == 200
    body = r.json()
    assert body["delta"] is not None and body["theoreticalPrice"] is not None


@pytest.mark.parametrize("bad", [
    {"underlyingPrice": "1e400"},          # overflow -> inf
    {"volatility": "1e400"},
    {"timeToMaturity": "-1e400"},
    {"strikePrice": 0},                     # gt=0
    {"underlyingPrice": -5},
    {"volatility": 0},
    {"exerciseRatio": 0},
    {"riskFreeRate": 5},                    # le=1
])
def test_nan_infinity_and_out_of_range_rejected_4xx(bad):
    r = client.post("/api/quant/calculate", json={**_OK, **bad})
    assert 400 <= r.status_code < 500


def test_configurable_upper_bounds_enforced(monkeypatch):
    monkeypatch.setattr(settings, "QUANT_CALC_MAX_SIGMA", 5.0)
    r = client.post("/api/quant/calculate", json={**_OK, "volatility": 9.0})
    assert 400 <= r.status_code < 500
    monkeypatch.setattr(settings, "QUANT_CALC_MAX_T_YEARS", 50.0)
    r = client.post("/api/quant/calculate", json={**_OK, "timeToMaturity": 999.0})
    assert 400 <= r.status_code < 500


def test_iv_solver_still_bounded_for_pathological_market_price():
    # market price far above intrinsic won't converge; solver is capped by QUANT_IV_MAX_ITERATIONS
    r = client.post("/api/quant/calculate", json={**_OK, "marketPrice": 1_000_000})
    assert r.status_code in (200, 422)  # never hangs, never 500


def test_garbage_symbol_on_analytics_route_is_400():
    r = client.get("/api/quant/" + "A" * 40)
    assert r.status_code == 400
    r2 = client.get("/api/quant/HP$G")
    assert r2.status_code == 400


def test_reconcile_symbol_list_is_capped(monkeypatch):
    monkeypatch.setattr(settings, "INSTRUMENTS_RECONCILE_MAX_SYMBOLS", 10)
    r = client.post("/api/instruments/reconcile", json=["SYM%03d" % i for i in range(11)])
    assert r.status_code == 400
    r_ok = client.post("/api/instruments/reconcile", json=["HPG", "VHM"])
    assert r_ok.status_code == 200
