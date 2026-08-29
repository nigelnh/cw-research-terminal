import json
import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse

from app.ai.ai_limits import ai_daily_budget, validate_chat_input
from app.ai.ai_schemas import ChatRequest, ChatResponse, HealthResponse
from app.ai.ai_system_prompt import build_system_prompt
from app.security.concurrency import GateTimeout, ai_call_gate
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
        ai_enabled=bool(settings.AI_ENABLED and settings.AI_PUBLIC_ENABLED),
        model=client.model,
        has_api_key=bool(client.api_key),
    )

@ai_router.post("/chat")
async def chat_endpoint(
    req: ChatRequest,
    client: OpenRouterClient = Depends(get_client),
):
    if not settings.AI_ENABLED or not settings.AI_PUBLIC_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="AI research assistant is currently disabled on this server."
        )

    if not client.api_key:
        raise HTTPException(
            status_code=503,
            detail="AI research assistant is not configured with an API key."
        )

    # Input hardening + optional process-local daily budget (rate limit + concurrency
    # gate are enforced separately - middleware tier 'ai' and ai_call_gate).
    validate_chat_input(req)
    ai_daily_budget.check_and_increment()

    if req.context is not None:
        try:
            from app.market_data.market_session import market_session
            from app.market_data.market_subscription_manager import subscription_manager

            sess_status = market_session.get_session_status().value
            sess_active = market_session.is_trading_active()
            health = subscription_manager.provider.get_health()

            if req.context.marketSession is None:
                req.context.marketSession = sess_status
            if req.context.marketSessionActive is None:
                req.context.marketSessionActive = sess_active
            if req.context.quoteDisplayEligible is None:
                req.context.quoteDisplayEligible = sess_active
            if req.context.feedConnected is None:
                req.context.feedConnected = bool(
                    health.get("trade_stream_connected")
                    or health.get("bid_ask_stream_connected")
                    or health.get("authenticated")
                )
            if req.context.serverTime is None:
                req.context.serverTime = market_session.get_vn_now().strftime("%Y-%m-%d %H:%M:%S (VN UTC+7)")
        except Exception as e:
            logger.debug(f"Error enriching AI context with market session: {e}")

    # Bounded tool execution: resolve canonical data needed for user query
    from app.ai.tools.tool_executor import ToolExecutor

    last_user_query = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
    tool_executor = ToolExecutor(max_tool_calls=4)
    executed_tools = await tool_executor.resolve_and_execute_proactive_tools(last_user_query, req.context)
    tool_results = [t["result"] for t in executed_tools]

    system_prompt = build_system_prompt(req.context, tool_results=tool_results if tool_results else None)
    raw_messages = [{"role": m.role, "content": m.content} for m in req.messages]

    if req.stream:
        async def event_generator():
            try:
                # Emit high-level tool activity labels
                for label in tool_executor.activity_labels:
                    act_payload = json.dumps({"type": "activity", "label": label, "done": False})
                    yield f"data: {act_payload}\n\n"

                async with ai_call_gate.acquire(settings.AI_ACQUIRE_TIMEOUT_SECONDS):
                    async for token in client.stream_chat(raw_messages, system_prompt):
                        payload = json.dumps({"content": token, "done": False})
                        yield f"data: {payload}\n\n"
                yield f"data: {json.dumps({'content': '', 'done': True})}\n\n"
            except GateTimeout:
                err_payload = json.dumps({"error": "The AI assistant is busy right now. Please retry shortly.", "done": True})
                yield f"data: {err_payload}\n\n"
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
        async with ai_call_gate.acquire(settings.AI_ACQUIRE_TIMEOUT_SECONDS):
            result = await client.generate_chat(raw_messages, system_prompt)
        return ChatResponse(
            role="assistant",
            content=result["content"],
            model=result["model"],
        )
    except GateTimeout:
        raise HTTPException(
            status_code=503, detail="The AI assistant is busy right now. Please retry shortly."
        )
    except AiProviderError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during AI chat execution")
        raise HTTPException(status_code=500, detail="Internal AI service error.")
