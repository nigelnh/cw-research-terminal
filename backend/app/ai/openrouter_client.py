import json
import logging
from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Dict, Any, Optional
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# --- Custom Sanitized Exceptions (Never leak API Keys or Raw Auth Payloads) ---

class AiProviderError(Exception):
    """Base error for AI inference operations."""
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

class AiConfigurationError(AiProviderError):
    def __init__(self, message: str = "AI research assistant is not configured or missing API key."):
        super().__init__(message, status_code=503)

class AiAuthenticationError(AiProviderError):
    def __init__(self, message: str = "AI inference provider authentication failed."):
        super().__init__(message, status_code=502)

class AiRateLimitError(AiProviderError):
    def __init__(self, message: str = "Rate limit reached for AI inference. Please wait a moment and try again."):
        super().__init__(message, status_code=429)

class AiModelUnavailableError(AiProviderError):
    def __init__(self, message: str = "Configured AI model is currently unavailable."):
        super().__init__(message, status_code=503)

class AiTimeoutError(AiProviderError):
    def __init__(self, message: str = "AI inference request timed out."):
        super().__init__(message, status_code=504)


# --- Abstract Provider Interface ---

class AiProvider(ABC):
    @abstractmethod
    async def generate_chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generates a complete non-streaming chat response."""
        pass

    @abstractmethod
    def stream_chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Yields incremental tokens from the model."""
        pass


# --- OpenRouter Client Implementation ---

class OpenRouterClient(AiProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._timeout = timeout

    @property
    def api_key(self) -> str:
        return self._api_key if self._api_key is not None else settings.OPENROUTER_API_KEY

    @property
    def model(self) -> str:
        return self._model if self._model is not None else settings.OPENROUTER_MODEL

    @property
    def base_url(self) -> str:
        url = self._base_url or settings.OPENROUTER_BASE_URL
        return url.rstrip("/")

    @property
    def timeout(self) -> float:
        return self._timeout if self._timeout is not None else settings.AI_TIMEOUT_SECONDS

    def _get_headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise AiConfigurationError()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if settings.OPENROUTER_SITE_URL:
            headers["HTTP-Referer"] = settings.OPENROUTER_SITE_URL
        if settings.OPENROUTER_APP_NAME:
            headers["X-Title"] = settings.OPENROUTER_APP_NAME

        return headers

    def _prepare_payload(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})
        formatted_messages.extend(messages)

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": settings.AI_TEMPERATURE,
            "stream": stream,
        }
        # Bound the paid output. OpenRouter passes max_tokens through to the model.
        max_out = int(getattr(settings, "AI_MAX_OUTPUT_TOKENS", 0) or 0)
        if max_out > 0:
            payload["max_tokens"] = max_out
        return payload

    async def generate_chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        headers = self._get_headers()
        payload = self._prepare_payload(messages, system_prompt, stream=False)
        endpoint = f"{self.base_url}/chat/completions"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(endpoint, headers=headers, json=payload)
            except httpx.TimeoutException:
                logger.error("OpenRouter request timed out.")
                raise AiTimeoutError()
            except httpx.RequestError as exc:
                logger.error(f"OpenRouter connection error: {exc.__class__.__name__}")
                raise AiProviderError("Failed to connect to AI provider.")

        if response.status_code == 401 or response.status_code == 403:
            logger.error("OpenRouter authentication failed (401/403).")
            raise AiAuthenticationError()
        elif response.status_code == 429:
            logger.warning("OpenRouter rate limit hit (429).")
            raise AiRateLimitError()
        elif response.status_code in (502, 503, 504, 404):
            logger.error(f"OpenRouter model unavailable ({response.status_code}).")
            raise AiModelUnavailableError()
        elif response.status_code != 200:
            logger.error(f"OpenRouter returned unexpected status: {response.status_code}")
            raise AiProviderError("AI inference provider returned an error.")

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            model_used = data.get("model", self.model)
            return {"content": content, "model": model_used, "role": "assistant"}
        except (KeyError, IndexError, ValueError) as exc:
            logger.error(f"Malformed response payload from OpenRouter: {exc}")
            raise AiProviderError("Received malformed response from AI provider.")

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        headers = self._get_headers()
        payload = self._prepare_payload(messages, system_prompt, stream=True)
        endpoint = f"{self.base_url}/chat/completions"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                async with client.stream("POST", endpoint, headers=headers, json=payload) as response:
                    if response.status_code == 401 or response.status_code == 403:
                        logger.error("OpenRouter authentication failed during stream.")
                        raise AiAuthenticationError()
                    elif response.status_code == 429:
                        logger.warning("OpenRouter rate limit during stream.")
                        raise AiRateLimitError()
                    elif response.status_code in (502, 503, 504, 404):
                        raise AiModelUnavailableError()
                    elif response.status_code != 200:
                        raise AiProviderError("AI provider error during stream.")

                    finish_reason: str | None = None
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            raw_data = line[6:].strip()
                            if raw_data == "[DONE]":
                                break
                            try:
                                parsed = json.loads(raw_data)
                                choice = parsed.get("choices", [{}])[0]
                                # Kept from every frame: only the final one carries it.
                                finish_reason = choice.get("finish_reason") or finish_reason
                                delta = choice.get("delta", {})
                                token = delta.get("content")
                                if token:
                                    yield token
                            except json.JSONDecodeError:
                                continue

                    # `length` means the model hit max_tokens and stopped mid-sentence.
                    # Without this the half-answer renders as though it were complete.
                    if finish_reason == "length":
                        logger.info("AI response truncated at max_tokens (%s)", settings.AI_MAX_OUTPUT_TOKENS)
                        yield "\n\n_(cut off at the response limit — ask me to continue, or for a shorter answer)_"
            except httpx.TimeoutException:
                logger.error("OpenRouter stream timed out.")
                raise AiTimeoutError()
            except httpx.RequestError as exc:
                logger.error(f"OpenRouter stream connection error: {exc.__class__.__name__}")
                raise AiProviderError("Network connection interrupted during AI response.")

# Global instance
openrouter_client = OpenRouterClient()
