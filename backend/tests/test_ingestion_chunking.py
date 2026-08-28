"""Pure-unit tests for provider-safe chunk generation and lookback clamping."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.persistence.ingestion.chunking import Chunk, generate_chunks, plan_backfill_windows


def _covers_exactly(chunks: list[Chunk], start: date, end: date) -> bool:
    """Union of inclusive [start,end] chunks == [start,end], contiguous, no overlap."""
    if not chunks:
        return start > end
    if chunks[0].start != start or chunks[-1].end != end:
        return False
    for a, b in zip(chunks, chunks[1:]):
        if b.start != a.end + timedelta(days=1):   # exactly one day after -> no gap, no overlap
            return False
    return all(c.start <= c.end for c in chunks)


def test_single_chunk_when_within_span():
    ch = generate_chunks(date(2026, 8, 1), date(2026, 8, 10), max_span_days=350)
    assert len(ch) == 1
    assert ch[0].start == date(2026, 8, 1) and ch[0].end == date(2026, 8, 10)
    assert ch[0].span_days == 9


def test_same_day_range():
    ch = generate_chunks(date(2026, 8, 5), date(2026, 8, 5), max_span_days=350)
    assert len(ch) == 1 and ch[0].span_days == 0


def test_exactly_max_span_is_one_chunk():
    start = date(2025, 1, 1)
    ch = generate_chunks(start, start + timedelta(days=350), max_span_days=350)
    assert len(ch) == 1 and ch[0].span_days == 350


def test_one_over_max_span_splits_into_two():
    start = date(2025, 1, 1)
    end = start + timedelta(days=351)
    ch = generate_chunks(start, end, max_span_days=350)
    assert [c.span_days for c in ch] == [350, 0]
    assert _covers_exactly(ch, start, end)


def test_boundary_no_missing_or_overlapping_day():
    start, end = date(2024, 8, 28), date(2026, 8, 28)  # 730 days
    ch = generate_chunks(start, end, max_span_days=350)
    assert len(ch) == 3
    assert [c.span_days for c in ch] == [350, 350, 28]
    assert _covers_exactly(ch, start, end)
    # explicit: chunk1 ends 2025-08-13, chunk2 starts 2025-08-14
    assert ch[0].end == date(2025, 8, 13)
    assert ch[1].start == date(2025, 8, 14)


def test_generate_chunks_rejects_reversed_range():
    with pytest.raises(ValueError):
        generate_chunks(date(2026, 8, 10), date(2026, 8, 1), max_span_days=350)


def test_seq_is_chronological_from_zero():
    ch = generate_chunks(date(2020, 1, 1), date(2023, 1, 1), max_span_days=200)
    assert [c.seq for c in ch] == list(range(len(ch)))
    assert all(ch[i].start < ch[i + 1].start for i in range(len(ch) - 1))


# ---- lookback clamp ---------------------------------------------------------
_TODAY = date(2026, 8, 28)


def test_plan_clamps_request_older_than_entitlement_horizon():
    plan = plan_backfill_windows(
        date(2024, 8, 28), _TODAY, today=_TODAY, max_span_days=350, max_lookback_days=360
    )
    assert plan.lookback_clamped is True
    assert plan.effective_start == _TODAY - timedelta(days=360)
    assert plan.clamp_note is not None and "different source" in plan.clamp_note
    assert plan.chunks[0].start == plan.effective_start
    assert plan.chunks[-1].end == _TODAY
    assert _covers_exactly(list(plan.chunks), plan.effective_start, _TODAY)


def test_plan_within_horizon_not_clamped():
    plan = plan_backfill_windows(
        _TODAY - timedelta(days=200), _TODAY, today=_TODAY, max_span_days=350, max_lookback_days=360
    )
    assert plan.lookback_clamped is False
    assert plan.effective_start == _TODAY - timedelta(days=200)
    assert len(plan.chunks) == 1


def test_plan_entirely_out_of_range_is_empty():
    plan = plan_backfill_windows(
        date(2020, 1, 1), date(2020, 6, 1), today=_TODAY, max_span_days=350, max_lookback_days=360
    )
    assert plan.is_empty
    assert plan.lookback_clamped is True


def test_plan_multichunk_within_one_year_when_span_small():
    plan = plan_backfill_windows(
        _TODAY - timedelta(days=360), _TODAY, today=_TODAY, max_span_days=200, max_lookback_days=360
    )
    assert not plan.lookback_clamped
    assert len(plan.chunks) == 2
    assert all(c.span_days <= 200 for c in plan.chunks)
