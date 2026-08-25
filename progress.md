# Project Progress: cw-research-platform

## Completed Changes
* **Full Repository Structure Cleanup, Historical Domain Reconstruction & Architecture Reorganization**:
  * **Git History Archaeology & Historical Formula Cataloging**:
    - Reconstructed all 30 historical CLI formulas and 54 Info-tab (Position Master) spreadsheet columns from Git history commits (`513b503`, `0004064`, `ddbb3e3`).
    - Created `docs/domain/historical_formula_catalog.md` ($F-01$ to $F-30$ with inputs, math, null behavior, and current status).
    - Created `docs/domain/info_tab_column_evolution.md` (54-column historical $\to$ current canonical mapping).
    - Created `docs/domain/stock_tab_evolution.md` (15-column historical Stock tab & underlying universe rules).
    - Created `docs/maintenance/legacy_migration_map.md` (archival traceability for legacy Node.js/Postgres server and formula scripts).
  * **Canonical Domain Contracts & Data Dictionaries**:
    - Created `docs/data_dictionary/warrant_info_columns.md` (end-to-end data lineage for every UI column).
    - Created `docs/data_dictionary/stock_tab_columns.md` (Stock research columns & universe lineage).
    - Created `docs/data_dictionary/market_fields.md` (raw vendor feed fields $\to$ normalized canonical quote mapping).
    - Created `docs/domain/warrant_domain_contract.md` (CW reference specifications, lifecycle, and corporate actions).
    - Created `docs/domain/stock_domain_contract.md` (underlying universe and mapping architecture).
    - Created `docs/domain/exercise_ratio_convention.md` (single source of truth for exercise ratio $k$).
    - Created `docs/domain/quant_model_contract.md` (BSM European Call, Bounded Bisection IV solver, Analytical Greeks, Standard Log-Return HV).
  * **Architecture & Repository Navigation Maps**:
    - Created `docs/architecture/system_overview.md`, `data_flow.md`, `backend_architecture.md`, `frontend_architecture.md`, `vendor_boundaries.md`.
    - Created `docs/maintenance/repository_map.md` (Fast lookup index for engineers and AI coding agents).
    - Created `docs/maintenance/cleanup_manifest.md` (File classification and safe deletion gate).
  * **Repository-Wide Filename Normalization to `snake_case`**:
    - Standardized all frontend components, tables, data providers, mappers, domain models, and fixtures to strict `snake_case`.
    - Renamed root `black-scholes_testing.py` to `audit/black_scholes_verification.py`.
    - Safely cleaned obsolete root `scratch/` probe scripts after full knowledge extraction.
  * **Verification & Zero-Regression Loop**:
    - Frontend Vitest: **96/96 passed (15 suites)**.
    - Frontend Production Build: **0 TypeScript/bundle errors (built in 1.05s)**.
    - Backend Pytest: **42/42 passed (100%)**.
    - Static Type Checking (Pyright): **0 errors, 0 warnings, 0 informations**.
    - Platform Architecture & Data Flow Audit: **36/36 passed (0 failures)**.

## Current State
* **Frontend Vitest Unit Suite**: **96/96 passing (15 suites)**.
* **Backend Pytest Suite**: **42/42 passing (100% pass)**.
* **Platform Architecture Audit**: **36/36 passing (0 failures)**.
* **Pyright Type Checker**: **0 errors, 0 warnings, 0 informations**.
* **Production Build**: **0 TypeScript/bundle errors**.
* **Canonical Subsystems**:
  - `backend/app/market_data/` (or `market/`): Live feed ingestion, normalization, threadsafe caching, WebSocket hub.
  - `backend/app/instruments/`: Authoritative Covered Warrant reference registry and corporate actions.
  - `backend/app/quant/`: BSM pricing, bounded IV bisection root solver, analytical Greeks, Log-Return HV.
  - `backend/app/ai/`: OpenRouter LLM copilot service & financial prompts.
  - `frontend/src/components/`: High-density terminal views (`MarketExplorer`, `InstrumentDrawer`, `ResearchUniverse`).

## Next Steps
1. Watchlist dynamic persistence and live instrument drawer quantitative analysis.
2. AI Research copilot quantitative prompt enhancements.
