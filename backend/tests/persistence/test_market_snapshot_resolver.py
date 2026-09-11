"""After-hours fallback resolver precedence (Step 13C)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.market_data.market_schemas import CanonicalQuote
from app.market_data.market_snapshot_resolver import MarketSnapshotResolver
from app.market_data.market_state import market_state
from app.persistence.repositories.instrument_repository import InstrumentRepository, InstrumentUpsert
from app.persistence.repositories.market_bar_repository import MarketBarRepository
from app.persistence.repositories.snapshot_repository import SnapshotRepository, SnapshotRow
from app.persistence.rows import BarUpsert

pytestmark = pytest.mark.asyncio

_VN = timezone(timedelta(hours=7))
_FRI = date(2026, 8, 28)     # last completed session at the frozen "now" below
_THU = date(2026, 8, 27)
_SAT_NOW = datetime(2026, 8, 29, 10, 0, tzinfo=_VN)       # market closed (weekend)
_ACTIVE_NOW = datetime(2026, 8, 28, 10, 0, tzinfo=_VN)    # Friday morning session


async def _seed_bars(sm, sym: str, rows: dict[date, float], *, pb="RAW", itype="STOCK"):
    async with sm() as s:
        iid = (await InstrumentRepository(s).upsert(
            InstrumentUpsert(symbol=sym, instrument_type=itype)
        )).id
        await s.commit()
    bars = [
        BarUpsert(
            instrument_id=iid, timeframe="1d",
            ts=datetime(d.year, d.month, d.day, 0, 0, tzinfo=_VN).astimezone(timezone.utc),
            open=c, high=c, low=c, close=c, volume=1000, price_basis=pb, source="fiinquant",
        )
        for d, c in rows.items()
    ]
    async with sm() as s:
        await MarketBarRepository(s).bulk_upsert_bars(bars)
        await s.commit()


async def _put_snapshot(sm, **kw):
    async with sm() as s:
        await SnapshotRepository(s).upsert(SnapshotRow(**kw))
        await s.commit()


@pytest.fixture
def resolver(engine, sessionmaker_, monkeypatch):
    from app.core.config import settings
    from app.market_data.history_read_service import history_read_service

    monkeypatch.setattr(settings, "SNAPSHOT_ENABLED", True)
    monkeypatch.setattr(settings, "DASHBOARD_FALLBACK_GAPFILL", False)
    monkeypatch.setattr(settings, "DATABASE_ENABLED", True)
    monkeypatch.setattr(settings, "HISTORY_SOURCE_MODE", "postgres_first")

    class _NoProvider:
        async def get_historical_bars(self, **kw):
            return []

    history_read_service.configure(engine=engine, sessionmaker=sessionmaker_, provider=_NoProvider())
    r = MarketSnapshotResolver()
    r.configure(sessionmaker_)
    yield r
    history_read_service.reset()


@pytest.fixture(autouse=True)
def _clear_market_state():
    market_state._quotes.clear()  # noqa: SLF001
    yield
    market_state._quotes.clear()  # noqa: SLF001


async def test_live_wins_during_active_session(resolver):
    market_state.restore_quote(CanonicalQuote(
        symbol="HPG", instrument_type="STOCK", last_price=30000.0, bid1_price=29900.0,
        ask1_price=30100.0, total_volume=5_000_000, trade_revision=3,
        received_timestamp=int(_ACTIVE_NOW.timestamp() * 1000),
    ))
    r = (await resolver.resolve_rows(["HPG"], now=_ACTIVE_NOW))[0]
    assert r.quote_prov.state.value == "LIVE"
    assert r.values["last_price"] == 30000.0
    assert r.is_realtime_eligible is True
    assert r.to_wire()["_trade_revision"] == 3


async def test_live_row_keeps_session_bands_and_exposes_reference_provenance(resolver):
    ts = int(_ACTIVE_NOW.timestamp() * 1000)
    market_state.restore_quote(CanonicalQuote(
        symbol="HPG", instrument_type="STOCK", last_price=30000.0,
        bid1_price=29900.0, ask1_price=30100.0,
        received_timestamp=ts, source_timestamp=ts,
    ))
    market_state.apply_reference_metadata(
        "HPG", session_date=_ACTIVE_NOW.date().isoformat(), reference_price=29800.0,
        ceiling_price=31850.0, floor_price=27750.0, observed_timestamp=ts,
    )

    r = (await resolver.resolve_rows(["HPG"], now=_ACTIVE_NOW))[0]
    wire = r.to_wire()

    assert wire["Ref"] == 29.8
    assert wire["Ceil"] == 31.85
    assert wire["Floor"] == 27.75
    assert wire["provenance"]["reference"]["source"] == "SESSION_REFERENCE"
    assert wire["displayState"] == "LIVE"


async def test_live_row_backfills_only_reference_from_previous_close(resolver, sessionmaker_):
    await _seed_bars(sessionmaker_, "HPG", {_THU: 29800.0})
    ts = int(_ACTIVE_NOW.timestamp() * 1000)
    market_state.restore_quote(CanonicalQuote(
        symbol="HPG", instrument_type="STOCK", last_price=30000.0,
        bid1_price=29900.0, ask1_price=30100.0,
        received_timestamp=ts, source_timestamp=ts,
    ))

    r = (await resolver.resolve_rows(["HPG"], now=_ACTIVE_NOW))[0]

    assert r.values["last_price"] == 30000.0
    assert r.values["reference_price"] is None
    assert r.values["ceiling_price"] is None
    assert r.values["floor_price"] is None
    assert r.reference_prov.source.value == "NONE"


async def test_live_row_preserves_partial_current_bands_while_backfilling_reference(
    resolver, sessionmaker_
):
    await _seed_bars(sessionmaker_, "HPG", {_THU: 29800.0})
    ts = int(_ACTIVE_NOW.timestamp() * 1000)
    market_state.restore_quote(CanonicalQuote(
        symbol="HPG", instrument_type="STOCK", last_price=30000.0,
        ceiling_price=31850.0, floor_price=None,
        reference_session_date=_ACTIVE_NOW.date().isoformat(),
        reference_timestamp=ts, received_timestamp=ts, source_timestamp=ts,
    ))

    r = (await resolver.resolve_rows(["HPG"], now=_ACTIVE_NOW))[0]

    assert r.values["reference_price"] is None
    assert r.values["ceiling_price"] == 31850.0
    assert r.values["floor_price"] is None
    assert r.values["last_price"] == 30000.0
    assert r.reference_prov.source.value == "SESSION_REFERENCE"


async def test_snapshot_wins_when_market_closed(resolver, sessionmaker_):
    await _put_snapshot(
        sessionmaker_, symbol="HPG", session_date=_FRI,
        captured_at=datetime(2026, 8, 28, 15, 2, tzinfo=_VN),
        source="SESSION_CLOSE", quality="FINAL", instrument_type="STOCK",
        reference_price=29800.0, last_price=30200.0, total_volume=7_000_000,
        bid1_price=30100.0, ask1_price=30300.0,
    )
    r = (await resolver.resolve_rows(["HPG"], now=_SAT_NOW))[0]
    assert r.quote_prov.state.value == "LAST_SESSION"
    assert r.quote_prov.source.value == "SNAPSHOT_FINAL"
    assert r.values["last_price"] == 30200.0
    assert r.values["bid1_price"] == 30100.0
    assert r.quote_prov.session_date == _FRI.isoformat()


async def test_closed_snapshot_uses_current_canonical_reference_bands(resolver, sessionmaker_):
    await _put_snapshot(
        sessionmaker_, symbol="HPG", session_date=_FRI,
        captured_at=datetime(2026, 8, 28, 15, 2, tzinfo=_VN),
        source="SESSION_CLOSE", quality="FINAL", instrument_type="STOCK",
        reference_price=29000.0, last_price=30200.0, total_volume=7_000_000,
        open_price=29900.0, high_price=30500.0, low_price=29700.0,
        price_change=1200.0, price_change_percent=0.041379,
        bid1_price=30100.0, ask1_price=30300.0,
    )
    ts = int(_SAT_NOW.timestamp() * 1000)
    market_state.restore_quote(CanonicalQuote(
        symbol="HPG", instrument_type="STOCK", last_price=99999.0,
        total_volume=999, received_timestamp=ts, source_timestamp=ts,
    ))
    market_state.apply_reference_metadata(
        "HPG", session_date=_FRI.isoformat(), reference_price=29800.0,
        ceiling_price=31850.0, floor_price=27750.0, observed_timestamp=ts,
    )

    r = (await resolver.resolve_rows(["HPG"], now=_SAT_NOW))[0]
    wire = r.to_wire()

    assert r.values["last_price"] == 30200.0
    assert r.values["total_volume"] == 7_000_000
    assert wire["Ref"] == 29.8
    assert wire["Ceil"] == 31.85
    assert wire["Floor"] == 27.75
    assert wire["provenance"]["reference"]["source"] == "SESSION_REFERENCE"


async def test_eod_bars_when_no_snapshot(resolver, sessionmaker_):
    await _seed_bars(sessionmaker_, "VHM", {_THU: 40000.0, _FRI: 41000.0})
    r = (await resolver.resolve_rows(["VHM"], now=_SAT_NOW))[0]
    assert r.quote_prov.state.value == "LAST_SESSION"
    assert r.quote_prov.source.value == "EOD_BARS"
    assert r.values["last_price"] == 41000.0
    assert r.values["reference_price"] is None
    assert r.values["price_change"] is None
    assert r.values.get("bid1_price") is None
    assert r.book_prov.state.value == "UNAVAILABLE"
    assert r.to_wire()["Bid1_Prc"] is None


async def test_fast_path_fills_book_only_snapshot_from_history_with_truthful_provenance(
    resolver, sessionmaker_
):
    await _seed_bars(sessionmaker_, "CHPG2617", {_THU: 490.0, _FRI: 440.0}, pb="RAW", itype="CW")
    await _put_snapshot(
        sessionmaker_, symbol="CHPG2617", session_date=_FRI,
        captured_at=datetime(2026, 8, 28, 15, 2, tzinfo=_VN),
        source="SESSION_CLOSE", quality="FINAL", instrument_type="CW",
        last_price=None, bid1_price=410.0, ask1_price=420.0,
    )
    row = (await resolver.resolve_rows(
        ["CHPG2617"], now=_SAT_NOW, enrich_snapshot_history=False
    ))[0]
    assert row.values["last_price"] == 440.0
    assert row.values["bid1_price"] == 410.0
    assert row.quote_prov.source.value == "EOD_BARS"
    assert row.book_prov.source.value == "SNAPSHOT_FINAL"


@pytest.mark.parametrize("snapshot_session", [_THU, _FRI])
async def test_daily_bars_fill_snapshot_fields_that_are_present_but_null(
    resolver, sessionmaker_, snapshot_session
):
    await _seed_bars(sessionmaker_, "VHM", {_THU: 40000.0, _FRI: 41000.0})
    await _put_snapshot(
        sessionmaker_, symbol="VHM", session_date=snapshot_session,
        captured_at=datetime(2026, 8, 27, 15, 2, tzinfo=_VN),
        source="SESSION_CLOSE", quality="FINAL", instrument_type="STOCK",
        reference_price=None, last_price=40500.0, open_price=None,
    )

    r = (await resolver.resolve_rows(["VHM"], now=_SAT_NOW))[0]

    # The persisted observed trade wins; missing fields are truly assigned from bars.
    assert r.values["last_price"] == (None if snapshot_session == _THU else 40500.0)
    assert r.values["open_price"] == (None if snapshot_session == _THU else 41000.0)
    expected_ref = None
    assert r.values["reference_price"] == expected_ref
    assert r.values["price_change"] == (None if expected_ref is None else 500.0)
    assert r.values["price_change_percent"] == (None if expected_ref is None else 0.0125)


async def test_no_trade_this_session_preserves_older_date(resolver, sessionmaker_):
    await _seed_bars(sessionmaker_, "VRE", {date(2026, 8, 26): 20000.0, _THU: 20500.0})
    r = (await resolver.resolve_rows(["VRE"], now=_SAT_NOW))[0]
    assert r.quote_prov.session_date == _FRI.isoformat()
    assert r.quote_prov.state.value == "UNAVAILABLE"
    assert r.values.get("last_price") is None


async def test_unavailable_when_nothing(resolver):
    r = (await resolver.resolve_rows(["ZZZ999"], now=_SAT_NOW))[0]
    assert r.quote_prov.state.value == "UNAVAILABLE"
    assert r.values.get("last_price") is None
    w = r.to_wire()
    assert w["Traded"] is None and w["displayState"] == "UNAVAILABLE"


async def test_diag_trace(resolver, sessionmaker_):
    await _seed_bars(sessionmaker_, "VJC", {_THU: 90000.0, _FRI: 91000.0})
    d = (await resolver.resolve_rows(["VJC"], now=_SAT_NOW, diag=True))[0].diag
    assert d["chosen"] == "EOD_BARS"
    assert any("C:EOD_BARS" in t for t in d["trace"])
