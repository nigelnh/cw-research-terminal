"""Resumable, quota-safe FiinQuant historical ingestion into PostgreSQL (Step 6).

Storage foundation is Step 5 (``app.persistence``). This package adds:

    seed        deterministic instrument seeding from the InstrumentRegistry
    chunking    provider-safe chronological request windows
    calendar    Vietnam trading-day helpers for gap classification (no invented holidays)
    retry       bounded exponential backoff + jitter, retryable-vs-not classification
    locks       PostgreSQL advisory-lock coordination for overlapping runs
    backfill    bounded historical backfill orchestration
    incremental incremental tail sync with a timeframe-aware safety overlap
    gaps        conservative gap detection + explicit repair
    service     IngestionService tying repositories + a HistoricalBarProvider together
    cli         ``python -m app.persistence.cli <command>``

The public ``/api/market/history`` API is NOT migrated to PostgreSQL here.
No full-universe backfill runs automatically.
"""
