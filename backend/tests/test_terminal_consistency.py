"""Regression matrix for session identity, entitlement evidence and price bounds."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import base64
import json
import pytest
from app.market_data.trading_calendar import VN_TZ, session_context
from app.market_data.feed_status import FeedAccess, classify_provider_error, redact_provider_text
from app.market_data.market_snapshot_resolver import MarketSnapshotResolver, ResolvedRow
from app.market_data.temporal import DataSource, DataTemporalState, FieldProvenance
from app.market_data.market_schemas import CanonicalQuote
from app.quant.quant_engine import LiveQuantEngine
from app.quant.quant_schemas import WarrantAnalytics

@pytest.mark.parametrize("instant,display,completed,phase", [
    ("2026-09-08T07:59:59", "2026-09-07", "2026-09-07", "PRE_OPEN"),
    ("2026-09-08T08:00:00", "2026-09-08", "2026-09-07", "PRE_OPEN"),
    ("2026-09-08T09:01:00", "2026-09-08", "2026-09-07", "ATO"),
    ("2026-09-08T10:00:00", "2026-09-08", "2026-09-07", "CONTINUOUS_AM"),
    ("2026-09-08T12:00:00", "2026-09-08", "2026-09-07", "LUNCH_BREAK"),
    ("2026-09-08T14:31:00", "2026-09-08", "2026-09-07", "ATC"),
    ("2026-09-08T15:01:00", "2026-09-08", "2026-09-08", "CLOSED"),
    ("2026-09-09T00:01:00", "2026-09-08", "2026-09-08", "PRE_OPEN"),
    ("2026-09-12T10:00:00", "2026-09-11", "2026-09-11", "CLOSED"),
    ("2026-09-02T10:00:00", "2026-08-28", "2026-08-28", "CLOSED"),
])
def test_one_session_clock(instant, display, completed, phase):
    current = datetime.fromisoformat(instant).replace(tzinfo=VN_TZ)
    context = session_context(current)
    assert context["displaySessionDate"] == display
    assert context["latestCompletedSession"] == completed
    assert context["marketPhase"] == phase
    assert datetime.fromisoformat(context["nextRolloverAt"]) > current

@pytest.mark.parametrize("text,code", [("401 Unauthorized", "AUTH_REQUIRED"),
    ("403 Forbidden", "DATASET_FORBIDDEN"), ("Service has expired", "ENTITLEMENT_EXPIRED"),
    ("Connection error", "UPSTREAM_UNAVAILABLE"), ("429 rate limit", "RATE_LIMITED")])
def test_access_errors_are_distinct(text, code):
    assert classify_provider_error(text) == code

def test_dataset_denial_does_not_deny_the_whole_feed():
    access = FeedAccess()
    access.record("breadth", "403 Forbidden")
    assert access.blocked("history") is None
    assert access.blocked("breadth") == "DATASET_FORBIDDEN"
    wire = access.wire(fresh=True, active=True, last_data_at="2026-09-08T10:00:00+07:00")
    assert wire["code"] == "AVAILABLE"
    assert wire["datasets"][0]["scope"] == "breadth"
    access.success("breadth")
    assert access.wire(fresh=True, active=True, last_data_at=None)["datasets"] == []

def test_entitlement_evidence_uses_existing_session_without_exposing_claims():
    part = base64.urlsafe_b64encode(json.dumps({"end_date": "07/09/2020", "secret": "private"}).encode()).decode().rstrip("=")
    access = FeedAccess()
    token = f"eyJhbGciOiJub25lIn0.{part}.signature"
    access.inspect_session(SimpleNamespace(access_token=token))
    assert access.blocked("history") == "ENTITLEMENT_EXPIRED"
    wire = json.dumps(access.wire(fresh=False, active=True, last_data_at=None))
    assert "private" not in wire and part not in wire
    assert token not in redact_provider_text(f"Authorization: Bearer {token}")
    access.success("profiles")
    assert access.blocked("history") == "ENTITLEMENT_EXPIRED"

@pytest.mark.asyncio
async def test_new_session_quant_never_uses_previous_eod(monkeypatch):
    current = datetime(2026, 9, 8, 9, 1, tzinfo=VN_TZ)
    monkeypatch.setattr("app.quant.quant_engine.get_vietnam_now", lambda: current)
    engine = LiveQuantEngine()
    live = WarrantAnalytics(symbol="CHPG2617", underlying_symbol="HPG", calculated_at=current.isoformat(),
        session_date="2026-09-08", is_available=False, unavailable_reason="NO_TRADE")
    monkeypatch.setattr(engine, "compute_warrant_analytics", AsyncMock(return_value=live))
    eod = AsyncMock()
    monkeypatch.setattr(engine, "compute_eod_analytics", eod)
    assert await engine.resolve_display_analytics("CHPG2617") is live
    eod.assert_not_awaited()

@pytest.mark.asyncio
async def test_old_quote_is_hidden_same_session_stale_is_retained(monkeypatch):
    current = datetime(2026, 9, 8, 10, tzinfo=VN_TZ)
    quote = CanonicalQuote(symbol="HPG", instrument_type="STOCK", last_price=25000,
        market_session_date="2026-09-07", trade_timestamp=int((current - timedelta(days=1)).timestamp() * 1000))
    monkeypatch.setattr("app.market_data.market_snapshot_resolver.market_state.get_quote", lambda _: quote)
    resolver = MarketSnapshotResolver()
    old = (await resolver.resolve_rows(["HPG"], now=current))[0]
    assert old.values.get("last_price") is None
    quote.market_session_date = "2026-09-08"
    quote.trade_timestamp = int((current - timedelta(minutes=15)).timestamp() * 1000)
    stale = (await resolver.resolve_rows(["HPG"], now=current))[0]
    assert stale.values["last_price"] == 25000 and stale.quote_prov.stale
    assert stale.quote_prov.as_of.startswith("2026-09-08T09:45")

@pytest.mark.asyncio
@pytest.mark.parametrize("ratio,ceiling,floor", [(3, 1430, 770), (3.5704, 1380, 820)])
async def test_hose_directional_rounding_and_session_gate(monkeypatch, ratio, ceiling, floor):
    spec = SimpleNamespace(metadata_verification=SimpleNamespace(value="VERIFIED_CURRENT"),
        is_adjusted=False, terms_effective_date=None, effective_ratio=ratio, underlying_symbol="HPG")
    monkeypatch.setattr("app.market_data.market_snapshot_resolver.instrument_registry.get_instrument", AsyncMock(return_value=spec))
    provenance = FieldProvenance(DataTemporalState.DERIVED, DataSource.SESSION_REFERENCE, session_date="2026-09-08")
    cw = ResolvedRow("CHPG2617", "CW", values={"reference_price": 1100}, reference_prov=provenance)
    stock = ResolvedRow("HPG", "STOCK", values={"reference_price": 25000, "ceiling_price": 26000, "floor_price": 24000}, reference_prov=provenance)
    await MarketSnapshotResolver()._derive_cw_bands([cw, stock])
    assert cw.values["ceiling_price"] == ceiling and cw.values["floor_price"] == floor
    stock.reference_prov = FieldProvenance(DataTemporalState.DERIVED, DataSource.SESSION_REFERENCE, session_date="2026-09-07")
    cw.values = {"reference_price": 1100}
    monkeypatch.setattr("app.market_data.market_snapshot_resolver.market_state.get_quote", lambda _: None)
    await MarketSnapshotResolver()._derive_cw_bands([cw, stock])
    assert cw.values.get("ceiling_price") is None

def test_tape_retention_spans_weekend():
    from app.market_data.traded_log import seconds_until_rollover
    friday = datetime(2026, 9, 11, 15, tzinfo=VN_TZ)
    assert friday + timedelta(seconds=seconds_until_rollover(friday)) == datetime(2026, 9, 14, 8, tzinfo=VN_TZ)
