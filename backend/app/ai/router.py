import json
import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse

from app.ai.schemas import ChatRequest, ChatResponse, HealthResponse
from app.ai.system_prompt import build_system_prompt
from app.ai.openrouter_client import (
    OpenRouterClient,
    openrouter_client,
    AiProviderError,
    AiConfigurationError,
    AiAuthenticationError,
    AiRateLimitError,
    AiModelUnavailableError,
    AiTimeoutError,
)
from app.core.config import settings

logger = logging.getLogger(__name__)
ai_router = APIRouter(prefix="/api/ai", tags=["AI Research Copilot"])

def get_client() -> OpenRouterClient:
    return openrouter_client

@ai_router.get("/health", response_model=HealthResponse)
async def ai_health(client: OpenRouterClient = Depends(get_client)):
    return HealthResponse(
        status="ok",
        ai_enabled=settings.AI_ENABLED,
        model=client.model,
        has_api_key=bool(client.api_key),
    )

@ai_router.post("/chat")
async def chat_endpoint(
    req: ChatRequest,
    client: OpenRouterClient = Depends(get_client),
):
    if not settings.AI_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="AI research assistant is currently disabled on this server."
        )

    if not client.api_key:
        raise HTTPException(
            status_code=503,
            detail="AI research assistant is not configured with an API key."
        )

    system_prompt = build_system_prompt(req.context)
    raw_messages = [{"role": m.role, "content": m.content} for m in req.messages]

    if req.stream:
        async def event_generator():
            try:
                async for token in client.stream_chat(raw_messages, system_prompt):
                    payload = json.dumps({"content": token, "done": False})
                    yield f"data: {payload}\n\n"
                yield f"data: {json.dumps({'content': '', 'done': True})}\n\n"
            except AiRateLimitError:
                err_payload = json.dumps({"error": "Rate limit reached. Please wait a moment and try again.", "done": True})
                yield f"data: {err_payload}\n\n"
            except AiModelUnavailableError:
                err_payload = json.dumps({"error": "Configured AI model is currently unavailable.", "done": True})
                yield f"data: {err_payload}\n\n"
            except AiTimeoutError:
                err_payload = json.dumps({"error": "AI request timed out. Please try again.", "done": True})
                yield f"data: {err_payload}\n\n"
            except AiProviderError as e:
                err_payload = json.dumps({"error": e.message, "done": True})
                yield f"data: {err_payload}\n\n"
            except Exception as e:
                logger.exception("Unexpected error during AI stream generation")
                err_payload = json.dumps({"error": "An unexpected error occurred while processing AI response.", "done": True})
                yield f"data: {err_payload}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    try:
        result = await client.generate_chat(raw_messages, system_prompt)
        return ChatResponse(
            role="assistant",
            content=result["content"],
            model=result["model"],
        )
    except AiProviderError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        logger.exception("Unexpected error during AI chat execution")
        raise HTTPException(status_code=500, detail="Internal AI service error.")
