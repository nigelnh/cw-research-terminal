import json
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.ai.openrouter_client import OpenRouterClient
from app.ai.ai_router import get_client

client = TestClient(app)

class MockHttpxResponse:
    def __init__(self, status_code: int, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self):
        return self._json_data

    def raise_for_status(self):
        pass


@pytest.fixture
def mock_openrouter_client():
    return OpenRouterClient(
        api_key="test-dummy-api-key",
        model="stealth/ox-alpha",
        base_url="https://openrouter.ai/api/v1",
    )


def test_ai_health_endpoint_zero_secret_leak(mock_openrouter_client):
    app.dependency_overrides[get_client] = lambda: mock_openrouter_client
    response = client.get("/api/ai/health")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["ai_enabled"] is True
    assert data["model"] == "stealth/ox-alpha"
    assert data["has_api_key"] is True
    # Verify no secret key value is present in payload
    assert "test-dummy-api-key" not in json.dumps(data)


def test_missing_api_key_returns_sanitized_503():
    empty_client = OpenRouterClient(api_key="", model="stealth/ox-alpha")
    app.dependency_overrides[get_client] = lambda: empty_client

    response = client.post(
        "/api/ai/chat",
        json={
            "messages": [{"role": "user", "content": "Explain implied volatility"}],
            "stream": False,
        },
    )
    app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.headers.get("X-AI-Error-Code") == "AI_DISABLED"
    data = response.json()
    assert "turned off" in data["detail"]
    assert "test-dummy" not in json.dumps(data)


@pytest.mark.asyncio
async def test_successful_non_streaming_chat(mock_openrouter_client):
    app.dependency_overrides[get_client] = lambda: mock_openrouter_client

    fake_response = MockHttpxResponse(
        status_code=200,
        json_data={
            "id": "gen-123",
            "model": "stealth/ox-alpha",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "IV Bid reflects the volatility derived from the best bid price.",
                    }
                }
            ],
        },
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = fake_response

        response = client.post(
            "/api/ai/chat",
            json={
                "messages": [{"role": "user", "content": "What is IV Bid?"}],
                "context": {
                    "activePage": "dashboard",
                    "selectedInstrument": {
                        "symbol": "CFPT2401",
                        "underlyingSymbol": "FPT",
                        "strikePrice": 125000,
                        "ivBid": 0.312,
                    },
                },
                "stream": False,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "assistant"
        assert "IV Bid reflects the volatility" in data["content"]
        assert data["model"] == "stealth/ox-alpha"

        # Verify OpenRouter payload was constructed properly
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["model"] == "stealth/ox-alpha"
        assert call_kwargs["headers"]["Authorization"] == "Bearer test-dummy-api-key"
        # Verify XML application context was included in system prompt
        system_msg = call_kwargs["json"]["messages"][0]
        assert system_msg["role"] == "system"
        assert "<application_context>" in system_msg["content"]
        assert "CFPT2401" in system_msg["content"]
        assert "0.312" in system_msg["content"]

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_upstream_401_403_sanitized_502(mock_openrouter_client):
    app.dependency_overrides[get_client] = lambda: mock_openrouter_client

    fake_response = MockHttpxResponse(
        status_code=401,
        json_data={"error": {"message": "Invalid API key"}},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = fake_response

        response = client.post(
            "/api/ai/chat",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": False,
            },
        )

        assert response.status_code == 502
        assert response.headers.get("X-AI-Error-Code") == "UPSTREAM_AUTH_ERROR"
        data = response.json()
        assert "provider authentication" in data["detail"]
        # Crucial security assertion: Never leak raw provider message or key
        assert "Invalid API key" not in data["detail"]
        assert "test-dummy" not in json.dumps(data)

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_upstream_429_rate_limit_handled(mock_openrouter_client):
    app.dependency_overrides[get_client] = lambda: mock_openrouter_client

    fake_response = MockHttpxResponse(
        status_code=429,
        json_data={"error": {"message": "Rate limit exceeded"}},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = fake_response

        response = client.post(
            "/api/ai/chat",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": False,
            },
        )

        assert response.status_code == 429
        assert response.headers.get("X-AI-Error-Code") == "UPSTREAM_RATE_LIMIT"
        data = response.json()
        assert "rate-limiting" in data["detail"]
        assert "Rate limit exceeded" not in json.dumps(data)

    app.dependency_overrides.clear()


def test_request_validation_bounds(mock_openrouter_client):
    app.dependency_overrides[get_client] = lambda: mock_openrouter_client
    # Both are rejected by the request schema (pydantic) before the handler runs.
    # 1. Empty messages list
    res_empty = client.post("/api/ai/chat", json={"messages": [], "stream": False})
    assert res_empty.status_code == 422

    # 2. Oversized message content (>8000 chars)
    res_oversized = client.post(
        "/api/ai/chat",
        json={"messages": [{"role": "user", "content": "A" * 9000}], "stream": False},
    )
    assert res_oversized.status_code == 422

    # 3. Message over AI_MAX_MESSAGE_LENGTH but under the schema's hard cap - caught by
    #    validate_chat_input, which the router normalises to INVALID_REQUEST (400) + header.
    res_mid = client.post(
        "/api/ai/chat",
        json={"messages": [{"role": "user", "content": "A" * 5000}], "stream": False},
    )
    assert res_mid.status_code == 400
    assert res_mid.headers.get("X-AI-Error-Code") == "INVALID_REQUEST"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_streaming_chat_generator(mock_openrouter_client):
    async def mock_stream_chat(messages, system_prompt):
        yield "Implied "
        yield "volatility "
        yield "analysis."

    with patch.object(mock_openrouter_client, "stream_chat", side_effect=mock_stream_chat):
        app.dependency_overrides[get_client] = lambda: mock_openrouter_client

        response = client.post(
            "/api/ai/chat",
            json={
                "messages": [{"role": "user", "content": "Explain IV"}],
                "stream": True,
            },
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        lines = response.text.strip().split("\n\n")
        assert len(lines) >= 3
        # Check first chunk
        chunk1 = json.loads(lines[0].replace("data: ", ""))
        assert chunk1["content"] == "Implied "
        assert chunk1["done"] is False

        # Check last chunk
        last_chunk = json.loads(lines[-1].replace("data: ", ""))
        assert last_chunk["done"] is True

        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_streaming_error_frame_carries_machine_code(mock_openrouter_client):
    """A provider failure before the first token yields a classified SSE error frame -
    machine code present, raw provider text absent."""
    from app.ai.openrouter_client import AiModelUnavailableError

    async def failing_stream(messages, system_prompt):
        raise AiModelUnavailableError("model xyz returned 404 upstream")
        yield  # pragma: no cover - generator marker

    with patch.object(mock_openrouter_client, "stream_chat", side_effect=failing_stream):
        app.dependency_overrides[get_client] = lambda: mock_openrouter_client
        response = client.post(
            "/api/ai/chat",
            json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
        )
        assert response.status_code == 200
        frames = [
            json.loads(l.replace("data: ", ""))
            for l in response.text.strip().split("\n\n")
            if l.startswith("data: ")
        ]
        err = next(f for f in frames if f.get("error"))
        assert err["code"] == "MODEL_UNAVAILABLE"
        assert err["done"] is True
        assert "404" not in response.text and "xyz" not in response.text
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_daily_budget_exhausted_maps_to_budget_code(mock_openrouter_client):
    from app.ai.ai_limits import ai_daily_budget

    app.dependency_overrides[get_client] = lambda: mock_openrouter_client
    original = ai_daily_budget.check_and_increment

    def boom():
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="The daily AI request budget for this server has been reached.")

    ai_daily_budget.check_and_increment = boom  # type: ignore[assignment]
    try:
        response = client.post(
            "/api/ai/chat",
            json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
        )
        assert response.status_code == 429
        assert response.headers.get("X-AI-Error-Code") == "AI_BUDGET_EXCEEDED"
    finally:
        ai_daily_budget.check_and_increment = original  # type: ignore[assignment]
        app.dependency_overrides.clear()


def test_ai_system_prompt_includes_market_session_and_tone_directives():
    from app.ai.ai_system_prompt import build_system_prompt
    from app.ai.ai_schemas import ResearchContextEnvelope, SelectedInstrumentContext

    ctx = ResearchContextEnvelope(
        activePage="dashboard",
        marketSession="LUNCH_BREAK",
        marketSessionActive=False,
        quoteDisplayEligible=False,
        feedConnected=True,
        selectedInstrument=SelectedInstrumentContext(
            symbol="CVHM2615",
            underlyingSymbol="VHM",
            strikePrice=45000.0,
            exerciseRatio=5.0,
            ivTrade=0.32,
            delta=0.45,
            gamma=0.002,
            theta=-1.2,
            vega=15.4,
            rho=0.8,
            moneyness=98.5,
            spreadPercent=0.85,
        ),
    )
    prompt = build_system_prompt(ctx)

    # Tone & persona directives
    assert "Warm, cheerful, approachable, competent, concise" in prompt
    assert "English-first product" in prompt
    assert "DEFAULT response language is English" in prompt
    assert "LUNCH_BREAK" in prompt
    assert "Live ticks are paused because the exchange is on lunch break" in prompt

    # Quantitative depth preserved
    assert "CVHM2615" in prompt
    assert "0.32" in prompt
    assert "0.45" in prompt
    assert "15.4" in prompt


@pytest.mark.asyncio
async def test_ai_chat_enriches_missing_session_context(mock_openrouter_client):
    app.dependency_overrides[get_client] = lambda: mock_openrouter_client

    fake_response = MockHttpxResponse(
        status_code=200,
        json_data={
            "id": "gen-456",
            "model": "stealth/ox-alpha",
            "choices": [{"message": {"role": "assistant", "content": "HPG is on lunch break."}}],
        },
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = fake_response

        # Context provided without marketSession
        response = client.post(
            "/api/ai/chat",
            json={
                "messages": [{"role": "user", "content": "Check HPG"}],
                "context": {
                    "activePage": "dashboard",
                    "watchlist": ["HPG", "VHM"],
                },
                "stream": False,
            },
        )

        assert response.status_code == 200
        call_kwargs = mock_post.call_args[1]
        system_msg = call_kwargs["json"]["messages"][0]["content"]

        # Verified: marketSession was automatically enriched by backend
        assert "marketSession" in system_msg
        assert "serverTime" in system_msg

    app.dependency_overrides.clear()
