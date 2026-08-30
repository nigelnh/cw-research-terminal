"""Step 14A — research data enrichment.

Controlled, code-owned backend ingestion of supplementary reference domains from public
exchange / broker APIs:

    HSX news           -> external_news
    VNDirect v4/events -> corporate_actions
    VNDirect profiles  -> company_profiles
    VNDirect prices    -> history validation only (no seeding this phase)

Design invariants:
  * The browser never contacts an upstream source. Flow is:
        external source -> this ingestion -> normalized PostgreSQL -> backend read API -> UI / AI
  * Read APIs / AI tools over these tables NEVER trigger an upstream call.
  * A source failure here cannot affect /healthz, realtime, quant, Redis, or the core
    market APIs. There is no app-startup coupling and no scheduler.
  * Zero additional FiinQuant traffic.
  * Every durable row is auditable: (source, source_id) natural key + timestamps + raw jsonb.
"""
