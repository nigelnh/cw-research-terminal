"""PostgreSQL persistence layer for durable historical market data.

Storage foundation only (Step 5). Nothing here runs unless ``settings.DATABASE_ENABLED``
is true; the realtime market path and the public historical API are untouched and still
served from FiinQuant.

Public surface:
    database.init_engine / dispose_engine / session_scope / get_session / health / ping
    models.Base + ORM models
    repositories.InstrumentRepository / MarketBarRepository / IngestionRepository
    bar_source.PostgresHistoricalBarSource  (implements HistoricalBarSource, not wired yet)
"""

from app.persistence import database
from app.persistence.bar_source import PostgresHistoricalBarSource
from app.persistence.models import Base, IngestionRun, IngestionState, Instrument, MarketBar
from app.persistence.repositories import (
    IngestionRepository,
    InstrumentRepository,
    MarketBarRepository,
)

__all__ = [
    "database",
    "Base",
    "Instrument",
    "MarketBar",
    "IngestionRun",
    "IngestionState",
    "InstrumentRepository",
    "MarketBarRepository",
    "IngestionRepository",
    "PostgresHistoricalBarSource",
]
