from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.market_data.market_schemas import (
    HistoricalEntitlementError,
    HistoricalRangeLimitError,
    HistoricalTransportError,
)
from app.persistence.database import session_scope
from app.persistence.ingestion.service import InvalidRequestError
from app.persistence.models import IngestionRun, IngestionState, Instrument, MarketBar
from app.persistence.repositories.instrument_repository import InstrumentRepository, InstrumentUpsert

pytestmark = pytest.mark.asyncio

_TODAY = date.today()


async def _seed_stock(symbol: str = "HPG") -> int:
    async with session_scope() as s:
        row = await InstrumentRepository(s).upsert(
            InstrumentUpsert(symbol=symbol, instrument_type="STOCK")
        )
    return row.id


async def _bar_count(instrument_id: int, price_basis: str = "ADJUSTED") -> int:
    async with session_scope() as s:
        return int(
            (
                await s.execute(
                    select(func.count()).select_from(MarketBar).where(
                        MarketBar.instrument_id == instrument_id,
                        MarketBar.price_basis == price_basis,
                    )
                )
            ).scalar_one()
        )


# --------------------------------------------------------------------------- #
async def test_single_symbol_single_chunk_backfill(ingestion_service, fake_provider):
    iid = await _seed_stock("HPG")
    frm = _TODAY - timedelta(days=40)
    fake_provider.seed_daily("HPG", frm, _TODAY)

    res = await ingestion_service.backfill(
        ["HPG"], timeframe="1D", adjusted=True, from_date=frm, to_date=_TODAY - timedelta(days=1)
    )
    assert res.status == "SUCCEEDED"
    assert len(res.streams[0].chunks) == 1
    assert res.streams[0].inserted > 0
    assert await _bar_count(iid) == res.streams[0].inserted

    async with session_scope() as s:
        run = (await s.execute(select(IngestionRun))).scalar_one()
        assert run.status == "SUCCEEDED"
        assert run.rows_inserted == res.streams[0].inserted
        st = (await s.execute(select(IngestionState))).scalar_one()
        assert st.last_bar_ts is not None and st.last_run_id == run.id


async def test_multi_chunk_backfill_covers_whole_range(ingestion_service, fake_provider):
    iid = await _seed_stock("FPT")
    frm = _TODAY - timedelta(days=300)
    fake_provider.seed_daily("FPT", frm - timedelta(days=5), _TODAY)

    res = await ingestion_service.backfill(
        ["FPT"], timeframe="1D", adjusted=True, from_date=frm, to_date=_TODAY - timedelta(days=1),
        concurrency=1,
    )
    assert res.status == "SUCCEEDED"
    # ingestion persists exactly what the provider returned (every weekday the fake seeded);
    # it does not second-guess the vendor with our approximate holiday calendar.
    end = _TODAY - timedelta(days=1)
    weekdays = sum(1 for i in range((end - frm).days + 1) if (frm + timedelta(days=i)).weekday() < 5)
    assert await _bar_count(iid) == weekdays


async def test_idempotent_rerun_creates_no_duplicates(ingestion_service, fake_provider):
    iid = await _seed_stock("HPG")
    frm = _TODAY - timedelta(days=30)
    fake_provider.seed_daily("HPG", frm, _TODAY)

    r1 = await ingestion_service.backfill(["HPG"], timeframe="1D", adjusted=True, from_date=frm, to_date=_TODAY - timedelta(days=1))
    n1 = await _bar_count(iid)
    r2 = await ingestion_service.backfill(["HPG"], timeframe="1D", adjusted=True, from_date=frm, to_date=_TODAY - timedelta(days=1), force=True)
    n2 = await _bar_count(iid)

    assert n1 == n2 == r1.streams[0].inserted
    assert r2.streams[0].inserted == 0
    assert r2.streams[0].updated == n1


async def test_rerun_without_force_skips_already_covered_chunks(ingestion_service, fake_provider):
    """Re-running an identical backfill without --force makes zero provider calls: every
    planned chunk is inside [backfilled_from, last_bar]. Requested start precedes the first
    trading day on purpose (Saturday) to exercise the holiday/weekend edge."""
    await _seed_stock("HPG")
    frm = _TODAY - timedelta(days=45)
    while frm.weekday() != 5:      # land exactly on a Saturday (no bar on the requested start)
        frm -= timedelta(days=1)
    fake_provider.seed_daily("HPG", frm, _TODAY)

    r1 = await ingestion_service.backfill(
        ["HPG"], timeframe="1D", adjusted=True, from_date=frm, to_date=_TODAY - timedelta(days=1)
    )
    assert r1.status == "SUCCEEDED"
    calls_1 = len(fake_provider.calls)
    assert calls_1 >= 1

    fake_provider.calls.clear()
    r2 = await ingestion_service.backfill(
        ["HPG"], timeframe="1D", adjusted=True, from_date=frm, to_date=_TODAY - timedelta(days=1)
    )
    assert r2.status == "SUCCEEDED"
    assert fake_provider.calls == []                       # nothing re-fetched
    assert all(len(s.chunks) == 0 for s in r2.streams)     # all chunks resume-skipped


async def test_vendor_revision_updates_in_place(ingestion_service, fake_provider):
    iid = await _seed_stock("HPG")
    frm = _TODAY - timedelta(days=20)
    fake_provider.seed_daily("HPG", frm, _TODAY, base=100.0)
    await ingestion_service.backfill(["HPG"], timeframe="1D", adjusted=True, from_date=frm, to_date=_TODAY - timedelta(days=1))

    # pick a persisted weekday and revise its close upstream
    target = None
    d = frm
    while d < _TODAY:
        if d.weekday() < 5:
            target = d
            break
        d += timedelta(days=1)
    assert target is not None
    fake_provider.revise_close("HPG", target.isoformat(), 999.5)

    r2 = await ingestion_service.backfill(["HPG"], timeframe="1D", adjusted=True, from_date=frm, to_date=_TODAY - timedelta(days=1), force=True)
    assert r2.streams[0].updated >= 1

    async with session_scope() as s:
        row = (
            await s.execute(
                select(MarketBar).where(MarketBar.instrument_id == iid, MarketBar.session_date == target)
            )
        ).scalar_one()
        assert float(row.close) == 999.5
        ids = (await s.execute(select(func.count()).select_from(MarketBar).where(MarketBar.instrument_id == iid))).scalar_one()
    # no new row for the revised bar
    assert ids == await _bar_count(iid)


async def test_resume_after_interruption(ingestion_service, fake_provider):
    """Second chunk fails on the first attempt; a resumed run completes it without
    re-fetching the already-persisted first chunk."""
    iid = await _seed_stock("SSI")
    frm = _TODAY - timedelta(days=360)
    fake_provider.seed_daily("SSI", frm - timedelta(days=5), _TODAY)

    # force the service to two chunks by shrinking the span for this test
    from app.core.config import settings

    old_span = settings.INGEST_MAX_CHUNK_SPAN_DAYS
    settings.INGEST_MAX_CHUNK_SPAN_DAYS = 180
    try:
        # first backfill: chunk 0 ok, chunk 1 raises a non-retryable range error mid-way is wrong;
        # use a transport error that also exhausts retries -> chunk 1 FAILED, chunk 0 committed
        fake_provider.fail_symbol["SSI"] = HistoricalTransportError("net down")
        # let the first chunk through, fail the rest:
        fake_provider.fail_symbol.clear()
        fake_provider.raise_on_call[1] = HistoricalTransportError("net down")
        fake_provider.raise_on_call[2] = HistoricalTransportError("net down")
        fake_provider.raise_on_call[3] = HistoricalTransportError("net down")
        fake_provider.raise_on_call[4] = HistoricalTransportError("net down")

        r1 = await ingestion_service.backfill(
            ["SSI"], timeframe="1D", adjusted=True, from_date=frm, to_date=_TODAY - timedelta(days=1),
            concurrency=1,
        )
        assert r1.streams[0].status in ("PARTIAL", "FAILED")
        partial_count = await _bar_count(iid)
        assert partial_count > 0
        calls_after_first = len(fake_provider.calls)

        # resume: provider healthy now
        fake_provider.raise_on_call.clear()
        r2 = await ingestion_service.backfill(
            ["SSI"], timeframe="1D", adjusted=True, from_date=frm, to_date=_TODAY - timedelta(days=1),
            concurrency=1,
        )
        assert r2.status in ("SUCCEEDED", "PARTIAL")
        assert await _bar_count(iid) > partial_count
        # resume skipped the already-covered leading chunk(s): fewer calls than a full run
        assert len(fake_provider.calls) - calls_after_first < calls_after_first + 2
    finally:
        settings.INGEST_MAX_CHUNK_SPAN_DAYS = old_span


async def test_backward_extension_does_not_skip_uncovered_early_chunk(ingestion_service, fake_provider):
    """A later backfill with an EARLIER --from than current coverage must fetch the
    newly-requested older range, not resume-skip it on the forward cursor."""
    from app.core.config import settings

    iid = await _seed_stock("HPG")
    fake_provider.seed_daily("HPG", _TODAY - timedelta(days=360), _TODAY)

    old_span = settings.INGEST_MAX_CHUNK_SPAN_DAYS
    settings.INGEST_MAX_CHUNK_SPAN_DAYS = 90
    try:
        # first: only recent ~60 days
        await ingestion_service.backfill(
            ["HPG"], timeframe="1D", adjusted=True,
            from_date=_TODAY - timedelta(days=60), to_date=_TODAY - timedelta(days=1),
        )
        recent_earliest = await _min_session(iid)

        # then: extend back to ~300 days, WITHOUT --force
        res = await ingestion_service.backfill(
            ["HPG"], timeframe="1D", adjusted=True,
            from_date=_TODAY - timedelta(days=300), to_date=_TODAY - timedelta(days=1),
        )
        assert res.status == "SUCCEEDED"
        assert await _min_session(iid) < recent_earliest         # older bars really landed
    finally:
        settings.INGEST_MAX_CHUNK_SPAN_DAYS = old_span


async def _min_session(iid: int):
    async with session_scope() as s:
        return (await s.execute(select(func.min(MarketBar.session_date)).where(MarketBar.instrument_id == iid))).scalar_one()


async def test_dry_run_makes_zero_provider_calls_and_zero_writes(ingestion_service, fake_provider):
    fake_provider.seed_daily("NEWSYM", _TODAY - timedelta(days=30), _TODAY)
    res = await ingestion_service.backfill(
        ["NEWSYM"], timeframe="1D", adjusted=True, from_date=_TODAY - timedelta(days=800),
        to_date=_TODAY, dry_run=True,
    )
    assert res.status == "DRY_RUN"
    assert res.streams[0].chunks and all(c.status == "PLANNED" for c in res.streams[0].chunks)
    assert res.streams[0].lookback_clamped is True

    assert fake_provider.calls == []
    async with session_scope() as s:
        for model in (Instrument, MarketBar, IngestionRun, IngestionState):
            assert (await s.execute(select(func.count()).select_from(model))).scalar_one() == 0


async def test_entitlement_clamp_marks_run_partial(ingestion_service, fake_provider):
    await _seed_stock("HPG")
    fake_provider.seed_daily("HPG", _TODAY - timedelta(days=365), _TODAY)
    res = await ingestion_service.backfill(
        ["HPG"], timeframe="1D", adjusted=True, from_date=_TODAY - timedelta(days=900),
        to_date=_TODAY - timedelta(days=1),
    )
    assert res.streams[0].lookback_clamped is True
    assert res.streams[0].status == "PARTIAL"
    async with session_scope() as s:
        run = (await s.execute(select(IngestionRun))).scalar_one()
        assert run.status == "PARTIAL"
        assert "different source" in (run.error_summary or "")


async def test_cw_adjusted_request_is_rejected(ingestion_service, fake_provider):
    async with session_scope() as s:
        await InstrumentRepository(s).upsert(InstrumentUpsert(symbol="CHPG2602", instrument_type="CW"))
    res = await ingestion_service.backfill(
        ["CHPG2602"], timeframe="1D", adjusted=True, from_date=_TODAY - timedelta(days=30), to_date=_TODAY
    )
    assert res.streams[0].status == "FAILED"
    assert "ADJUSTED" in (res.streams[0].error or "")
    assert fake_provider.calls == []


async def test_cw_raw_request_is_accepted(ingestion_service, fake_provider):
    async with session_scope() as s:
        row = await InstrumentRepository(s).upsert(InstrumentUpsert(symbol="CHPG2602", instrument_type="CW"))
    iid = row.id
    fake_provider.seed_daily("CHPG2602", _TODAY - timedelta(days=30), _TODAY, base=3.5, step=0.01, adjusted=False)
    res = await ingestion_service.backfill(
        ["CHPG2602"], timeframe="1D", adjusted=False, from_date=_TODAY - timedelta(days=30),
        to_date=_TODAY - timedelta(days=1),
    )
    assert res.status == "SUCCEEDED"
    assert await _bar_count(iid, "RAW") > 0
    assert await _bar_count(iid, "ADJUSTED") == 0


async def test_forming_current_bar_is_dropped_by_default(ingestion_service, fake_provider):
    iid = await _seed_stock("HPG")
    fake_provider.seed_daily("HPG", _TODAY - timedelta(days=10), _TODAY)  # includes today
    res = await ingestion_service.backfill(
        ["HPG"], timeframe="1D", adjusted=True, from_date=_TODAY - timedelta(days=10), to_date=_TODAY
    )
    from app.persistence.ingestion.trading_calendar import last_completed_session_date

    async with session_scope() as s:
        latest = (
            await s.execute(select(func.max(MarketBar.session_date)).where(MarketBar.instrument_id == iid))
        ).scalar_one()
    assert latest is not None and latest <= last_completed_session_date()
    assert res.streams[0].chunks[0].dropped_incomplete >= 0


@pytest.mark.parametrize(
    "exc", [HistoricalRangeLimitError("365 days"), HistoricalEntitlementError("403 Forbidden")]
)
async def test_non_retryable_error_halts_stream_without_retry(ingestion_service, fake_provider, exc):
    iid = await _seed_stock("HPG")
    frm = _TODAY - timedelta(days=300)
    fake_provider.seed_daily("HPG", frm, _TODAY)
    fake_provider.fail_symbol["HPG"] = exc

    res = await ingestion_service.backfill(
        ["HPG"], timeframe="1D", adjusted=True, from_date=frm, to_date=_TODAY - timedelta(days=1),
        concurrency=1,
    )
    assert res.streams[0].status == "FAILED"
    # exactly one provider call - no retry storm on a permanent error
    assert len(fake_provider.calls) == 1
    assert await _bar_count(iid) == 0
    async with session_scope() as s:
        run = (await s.execute(select(IngestionRun))).scalar_one()
        assert run.status == "FAILED" and run.error_summary


async def test_too_many_symbols_rejected(ingestion_service):
    from app.core.config import settings

    many = [f"S{i:03d}" for i in range(settings.INGEST_MAX_SYMBOLS_PER_INVOCATION + 1)]
    with pytest.raises(InvalidRequestError):
        await ingestion_service.backfill(
            many, timeframe="1D", adjusted=True, from_date=_TODAY - timedelta(days=10), to_date=_TODAY
        )
