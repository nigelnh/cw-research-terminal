import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.ai.ai_errors import AiErrorCode, classify, http_status, user_message
from app.ai.ai_limits import ai_daily_budget, validate_chat_input
from app.ai.ai_schemas import ChatRequest, ChatResponse, HealthResponse
from app.ai.ai_system_prompt import build_system_prompt
from app.ai.openrouter_client import (
    AiProviderError,
    OpenRouterClient,
    openrouter_client,
)
from app.core.config import settings
from app.security.concurrency import GateTimeout, ai_call_gate

logger = logging.getLogger(__name__)
ai_router = APIRouter(prefix="/api/ai", tags=["AI Research Copilot"])

AI_ERROR_CODE_HEADER = "X-AI-Error-Code"


def _raise_ai_http(code: AiErrorCode, log_detail: str) -> None:
    """Raise a sanitized HTTPException carrying the machine code as a header. The body
    `detail` is the short user-facing string; the real reason goes only to the server log."""
    logger.warning("AI request rejected [%s]: %s", code.value, log_detail)
    raise HTTPException(
        status_code=http_status(code),
        detail=user_message(code),
        headers={AI_ERROR_CODE_HEADER: code.value},
    )


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
        _raise_ai_http(AiErrorCode.AI_DISABLED, "AI_ENABLED/AI_PUBLIC_ENABLED is off")

    if not client.api_key:
        _raise_ai_http(AiErrorCode.AI_DISABLED, "no OpenRouter API key configured on this server")

    # Input hardening + optional process-local daily budget (rate limit + concurrency
    # gate are enforced separately - middleware tier 'ai' and ai_call_gate).
    try:
        validate_chat_input(req)
    except HTTPException as e:
        _raise_ai_http(classify(e), f"input validation failed: {e.detail}")
    try:
        ai_daily_budget.check_and_increment()
    except HTTPException as e:
        _raise_ai_http(classify(e), "daily AI request budget reached")

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

    system_prompt = build_system_prompt(
        req.context,
        tool_results=tool_results if tool_results else None,
        latest_user_message=last_user_query,
    )
    raw_messages = [{"role": m.role, "content": m.content} for m in req.messages]

    # Weak free models drift to the thread's dominant language. Reinforce the
    # deterministic per-reply language (from the user's OWN latest message) right where
    # the model looks last — appended to the final user turn.
    from app.ai.ai_system_prompt import detect_reply_language

    _reply_lang = detect_reply_language(last_user_query)
    for _m in reversed(raw_messages):
        if _m["role"] == "user":
            _tag = "Trả lời bằng tiếng Việt." if _reply_lang == "Vietnamese" else "Respond in English."
            _m["content"] = f"{_m['content']}\n\n[{_tag}]"
            break

    if req.stream:
        async def event_generator():
            stream_started = False

            def sse(obj: dict) -> str:
                return f"data: {json.dumps(obj)}\n\n"

            try:
                # User-visible research trace. Tools have already executed (bounded,
                # read-only, pre-stream); emit start/complete for each so the UI can show
                # what was done. Payloads are sanitised counts/status — never raw results,
                # never model reasoning.
                for step in tool_executor.trace:
                    yield sse({
                        "type": "tool_start", "tool": step["tool"],
                        "display_name": step["display_name"], "context": step["context"],
                    })
                    yield sse({
                        "type": "tool_complete", "tool": step["tool"],
                        "display_name": step["display_name"],
                        "result_summary": step["result_summary"],
                        "duration_ms": step["duration_ms"], "ok": step["ok"],
                    })
                yield sse({
                    "type": "status",
                    "label": "Synthesizing answer" if tool_executor.trace else "Thinking",
                })

                async with ai_call_gate.acquire(settings.AI_ACQUIRE_TIMEOUT_SECONDS):
                    async for token in client.stream_chat(raw_messages, system_prompt):
                        stream_started = True
                        yield sse({"content": token, "done": False})
                yield sse({"type": "answer_complete", "content": "", "done": True})
            except Exception as e:
                code = classify(e, stream_started=stream_started)
                detail = getattr(e, "message", None) or getattr(e, "detail", None) or str(e)
                if code in (AiErrorCode.INTERNAL_ERROR, AiErrorCode.STREAM_INTERRUPTED):
                    logger.exception("AI stream failed [%s]", code.value)
                else:
                    logger.warning("AI stream failed [%s]: %s", code.value, detail)
                yield sse({
                    "type": "error", "error": user_message(code),
                    "code": code.value, "done": True,
                })

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
    except HTTPException:
        raise
    except (GateTimeout, AiProviderError) as e:
        code = classify(e)
        _raise_ai_http(code, getattr(e, "message", None) or str(e))
    except Exception as e:
        logger.exception("Unexpected error during AI chat execution")
        _raise_ai_http(AiErrorCode.INTERNAL_ERROR, str(e))
