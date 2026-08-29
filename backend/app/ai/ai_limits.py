"""AI cost-protection helpers: input bounds + a process-local daily request budget.

The HTTP rate limit (tier "ai", fail-closed) and the global concurrency gate
(``ai_call_gate``) live elsewhere. This module only covers per-request input validation
and an optional single-process daily cap.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.ai.ai_schemas import ChatRequest
from app.core.config import settings


def validate_chat_input(req: ChatRequest) -> None:
    """Deterministic 400/413 for oversized or abusive AI input."""
    n = len(req.messages)
    if n == 0:
        raise HTTPException(status_code=422, detail="At least one message is required.")
    if n > settings.AI_MAX_MESSAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Conversation too long: {n} messages (max {settings.AI_MAX_MESSAGES}).",
        )

    total_chars = 0
    for m in req.messages:
        length = len(m.content)
        if length > settings.AI_MAX_MESSAGE_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A message exceeds the {settings.AI_MAX_MESSAGE_LENGTH}-character limit.",
            )
        total_chars += length
    if total_chars > settings.AI_MAX_INPUT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Total prompt is {total_chars} characters (max {settings.AI_MAX_INPUT_CHARS}).",
        )

    # bound the context envelope's symbol lists too
    ctx = req.context
    if ctx is not None:
        for field in ("watchedSymbols", "watchlist"):
            vals = getattr(ctx, field, None) or []
            if len(vals) > 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"context.{field} has too many entries.",
                )


class _DailyBudget:
    """Single-process UTC-day request counter. Not shared across workers - documented."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._day = ""
        self._count = 0

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def check_and_increment(self) -> None:
        budget = int(settings.AI_DAILY_REQUEST_BUDGET)
        if budget <= 0:
            return
        with self._lock:
            today = self._today()
            if today != self._day:
                self._day = today
                self._count = 0
            if self._count >= budget:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="The daily AI request budget for this server has been reached.",
                    headers={"Retry-After": "3600"},
                )
            self._count += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "enabled": int(settings.AI_DAILY_REQUEST_BUDGET) > 0,
                "budget": int(settings.AI_DAILY_REQUEST_BUDGET),
                "used_today": self._count if self._day == self._today() else 0,
            }


ai_daily_budget = _DailyBudget()
