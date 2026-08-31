"""Step 14A/B — research data enrichment.

Controlled, code-owned backend ingestion of supplementary reference domains from public
exchange / broker APIs:

    HOSE news              -> external_news        (14A recent + 14B ~24-month corpus)
    VNDirect v4/events     -> company_events        (dividends / meetings / listings)
    SSI company events     -> company_events        (+ financial statements, insider txns)
    VNDirect profiles      -> company_profiles
    VNDirect prices        -> history validation only

Design invariants:
  * The browser never contacts an upstream source. Flow is:
        external source -> this ingestion -> normalized PostgreSQL -> backend read API -> UI / AI
  * Read APIs / AI tools over these tables NEVER trigger an upstream call.
  * A source failure here cannot affect /healthz, realtime, quant, Redis, or the core
    market APIs. There is no app-startup coupling and no scheduler.
  * Zero additional FiinQuant traffic.
  * Every durable row is auditable: (source, source_id) natural key + timestamps + raw jsonb.
"""
