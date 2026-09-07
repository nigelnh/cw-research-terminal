"""Read-only research-enrichment tools for the Assistant (Step 14A).

Both tools read ONLY the project's PostgreSQL enrichment tables (populated by controlled
backend ingestion). They never contact an upstream source and never trigger a fetch.

Causal restraint: output is framed as "disclosed / effective near this period". The model
must not assert that a disclosure or corporate action *caused* a price move. Every payload
carries ``provenance`` and a ``causal_note`` the system prompt already reinforces.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.core.config import settings
from app.persistence import database as persistence_db

logger = logging.getLogger(__name__)

_CAUSAL_NOTE = (
    "These items were disclosed/effective near the stated dates. Do not assert they caused "
    "any price movement; describe timing and content only."
)


def _unavailable(kind: str) -> Dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "message": f"{kind} store is not configured for this deployment.",
        "provenance": "RESEARCH_ENRICHMENT",
    }


async def get_news(
    symbol: str | None = None,
    limit: int | None = None,
    lang: str = "vi",
    query: str | None = None,
) -> Dict[str, Any]:
    """Disclosures for a symbol, ranked against `query` when one is supplied.

    Without `query` this is the newest N for the ticker, which answers "any news?" but not
    "any dilution risk?" - the relevant filing is often nowhere near the top by date. With
    it, the repository ranks by full-text relevance blended with recency.
    """
    if not persistence_db.is_configured():
        return _unavailable("News")
    n = max(1, min(int(limit or settings.AI_NEWS_MAX_RESULTS), int(settings.AI_NEWS_MAX_RESULTS)))
    lang = lang if lang in ("vi", "en") else "vi"
    sym = symbol.strip().upper() if symbol else None
    text_query = (query or "").strip() or None

    from app.enrichment import repository as repo
    from app.enrichment.english import category_en, headline_en
    from app.enrichment.normalize import strip_html

    maker = persistence_db.get_sessionmaker()
    async with maker() as s:
        rows = await repo.list_news(s, symbol=sym, lang=lang, limit=n, query=text_query)
        # A narrow question can legitimately match nothing; fall back to the recent tape
        # so the model still has context instead of concluding there is no coverage.
        if text_query and not rows:
            rows = await repo.list_news(s, symbol=sym, lang=lang, limit=n)
            text_query = None

    items = []
    for r in rows:
        syms = r.symbols or []
        t_en, exact = headline_en(r.title, category=r.category, symbol=(syms[0] if syms else None))
        items.append(
            {
                "title_en": t_en,                       # English disclosure-type rendering
                "title_en_exact": exact,                 # False -> a classification, not a translation
                "category_en": category_en(r.category),
                "title_original": r.title,               # verbatim Vietnamese (provenance)
                "summary_original": strip_html(r.summary_html),
                "source_language": r.lang or "vi",
                "symbols": syms,
                "published_at": r.published_at.date().isoformat() if r.published_at else None,
                "source": r.source,
            }
        )
    return {
        "symbol": sym,
        "count": len(rows),
        "items": items,
        # Tells the model whether these rows were selected FOR the question or are simply
        # the latest, so it does not present a recency dump as targeted evidence.
        "ranked_by": "RELEVANCE_AND_RECENCY" if text_query else "RECENCY",
        "matched_query": text_query,
        "causal_note": _CAUSAL_NOTE,
        "provenance": "RESEARCH_ENRICHMENT",
    }


async def get_corporate_actions(symbol: str, limit: int | None = None) -> Dict[str, Any]:
    if not symbol or not symbol.strip():
        return {"status": "INVALID_ARGUMENT", "message": "symbol is required", "provenance": "RESEARCH_ENRICHMENT"}
    if not persistence_db.is_configured():
        return _unavailable("Corporate actions")
    sym = symbol.strip().upper()
    n = max(1, min(int(limit or settings.AI_CORPORATE_ACTIONS_MAX_RESULTS), int(settings.AI_CORPORATE_ACTIONS_MAX_RESULTS)))

    from app.enrichment import repository as repo
    from app.enrichment.english import event_label_en

    maker = persistence_db.get_sessionmaker()
    async with maker() as s:
        rows = await repo.list_corporate_actions(s, symbol=sym, limit=n)

    def _d(v):
        return v.isoformat() if v else None

    return {
        "symbol": sym,
        "count": len(rows),
        "items": [
            {
                "label": event_label_en(r.event_class, r.event_type),
                "type": r.event_type,
                "event_class": r.event_class,
                "status": r.status,
                "ex_date": _d(r.ex_date),
                "record_date": _d(r.record_date),
                "payment_date": _d(r.payment_date),
                "cash_amount_vnd_per_share": float(r.cash_amount_vnd) if r.cash_amount_vnd is not None else None,
                "ratio_pct": float(r.ratio_pct) if r.ratio_pct is not None else None,
                "dividend_year": r.dividend_year,
                "note_original": r.note,
                "source_language": "vi",
                "source": r.source,
            }
            for r in rows
        ],
        "causal_note": _CAUSAL_NOTE,
        "provenance": "RESEARCH_ENRICHMENT",
    }


async def get_company_events(
    symbol: str, event_class: str | None = None, limit: int | None = None
) -> Dict[str, Any]:
    """Full company-event stream: dividends, meetings, listings, financial-statement
    disclosures and insider transactions. A financial-statement disclosure or an insider
    trade is a company *event*, not a corporate action, and never a cause of a price move.
    """
    if not symbol or not symbol.strip():
        return {"status": "INVALID_ARGUMENT", "message": "symbol is required", "provenance": "RESEARCH_ENRICHMENT"}
    if not persistence_db.is_configured():
        return _unavailable("Company events")
    sym = symbol.strip().upper()
    n = max(1, min(int(limit or settings.AI_CORPORATE_ACTIONS_MAX_RESULTS), int(settings.AI_CORPORATE_ACTIONS_MAX_RESULTS)))
    classes = [c.strip().upper() for c in event_class.split(",")] if event_class else None

    from app.enrichment import repository as repo
    from app.enrichment.english import event_label_en

    maker = persistence_db.get_sessionmaker()
    async with maker() as s:
        rows = await repo.list_company_events(s, symbol=sym, limit=n, classes=classes)

    def _d(v):
        return v.isoformat() if v else None

    return {
        "symbol": sym,
        "count": len(rows),
        "items": [
            {
                "label": event_label_en(r.event_class, r.event_type),
                "event_class": r.event_class,
                "type": r.event_type,
                "name_original": r.event_name,
                "source_language": "vi",
                "status": r.status,
                "public_date": _d(r.public_date),
                "ex_date": _d(r.ex_date),
                "record_date": _d(r.record_date),
                "ratio_pct": float(r.ratio_pct) if r.ratio_pct is not None else None,
                "cash_amount_vnd_per_share": float(r.cash_amount_vnd) if r.cash_amount_vnd is not None else None,
                "value_text": r.value_text,
                "note_original": (r.note[:280] if r.note else None),
                "source": r.source,
            }
            for r in rows
        ],
        "causal_note": _CAUSAL_NOTE,
        "provenance": "RESEARCH_ENRICHMENT",
    }
