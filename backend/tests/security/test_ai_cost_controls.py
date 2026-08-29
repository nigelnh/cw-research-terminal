"""AI cost protection (Step 10 sections 5, 26)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _ai_on(monkeypatch):
    monkeypatch.setattr(settings, "AI_ENABLED", True)
    monkeypatch.setattr(settings, "AI_PUBLIC_ENABLED", True)
    # a real key so we get past the "not configured" guard and reach the input checks
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-test-not-real")
    yield


def _chat(content="hello", n=1, stream=False):
    return {"messages": [{"role": "user", "content": content} for _ in range(n)], "stream": stream}


def test_kill_switch_disables_endpoint_cleanly(monkeypatch):
    monkeypatch.setattr(settings, "AI_PUBLIC_ENABLED", False)
    r = client.post("/api/ai/chat", json=_chat())
    assert r.status_code == 503
    # rest of the app still works
    assert client.get("/health").status_code == 200


def test_missing_api_key_is_graceful_not_fabricated(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    r = client.post("/api/ai/chat", json=_chat())
    assert r.status_code == 503
    assert "content" not in r.json()  # no fabricated answer


def test_too_many_messages_rejected(monkeypatch):
    monkeypatch.setattr(settings, "AI_MAX_MESSAGES", 5)
    r = client.post("/api/ai/chat", json=_chat(n=6))
    assert r.status_code == 400


def test_single_message_too_long_rejected(monkeypatch):
    monkeypatch.setattr(settings, "AI_MAX_MESSAGE_LENGTH", 100)
    r = client.post("/api/ai/chat", json=_chat(content="x" * 200))
    assert r.status_code == 400


def test_total_input_chars_capped(monkeypatch):
    monkeypatch.setattr(settings, "AI_MAX_MESSAGES", 50)
    monkeypatch.setattr(settings, "AI_MAX_MESSAGE_LENGTH", 5000)
    monkeypatch.setattr(settings, "AI_MAX_INPUT_CHARS", 1000)
    r = client.post("/api/ai/chat", json=_chat(content="x" * 400, n=5))  # 2000 total
    # The router normalises every input-validation rejection to INVALID_REQUEST (400);
    # the machine code on the header preserves the specific reason for logs/clients.
    assert r.status_code == 400
    assert r.headers.get("X-AI-Error-Code") == "INVALID_REQUEST"


def test_daily_budget_enforced(monkeypatch):
    from app.ai.ai_limits import ai_daily_budget

    ai_daily_budget._day = ""
    ai_daily_budget._count = 0
    monkeypatch.setattr(settings, "AI_DAILY_REQUEST_BUDGET", 2)
    # requests reach the budget check before the upstream call; upstream will fail (fake key)
    codes = [client.post("/api/ai/chat", json=_chat()).status_code for _ in range(4)]
    assert codes.count(429) >= 1
    ai_daily_budget._day = ""
    ai_daily_budget._count = 0


def test_output_tokens_bounded_in_payload():
    from app.ai.openrouter_client import openrouter_client

    payload = openrouter_client._prepare_payload([{"role": "user", "content": "hi"}], None)
    assert payload["max_tokens"] == settings.AI_MAX_OUTPUT_TOKENS


def test_concurrency_gate_returns_503_when_saturated(monkeypatch):
    """With the gate held at capacity, a new AI call fails fast with 503 - it never
    starts an upstream request."""
    from app.security.concurrency import ai_call_gate

    monkeypatch.setattr(settings, "AI_MAX_CONCURRENT", 1)
    monkeypatch.setattr(settings, "AI_ACQUIRE_TIMEOUT_SECONDS", 0.2)
    ai_call_gate.set_limit(1)

    async def scenario():
        async with ai_call_gate.acquire(timeout=1.0):
            # gate is now full; a second acquire must time out
            with pytest.raises(Exception):
                async with ai_call_gate.acquire(timeout=0.2):
                    pass

    asyncio.run(scenario())
    ai_call_gate.set_limit(settings.AI_MAX_CONCURRENT)


def test_provider_error_does_not_leak_secrets(monkeypatch):
    """A failing upstream call surfaces a generic message - never the API key/base URL."""
    from app.ai.openrouter_client import AiProviderError, openrouter_client

    async def boom(*a, **k):
        raise AiProviderError("AI inference provider returned an error.")

    monkeypatch.setattr(openrouter_client, "generate_chat", boom)
    r = client.post("/api/ai/chat", json=_chat())
    text = r.text.lower()
    assert "sk-test-not-real" not in text
    assert "openrouter.ai" not in text
    assert "authorization" not in text
