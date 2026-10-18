import logging
from typing import Any, Dict, List, Optional
from config import settings

logger = logging.getLogger(__name__)


class GroqError(Exception):
    """Base exception for Groq client operations."""
    pass


class GroqConfigurationError(GroqError):
    """Exception raised when Groq API key is missing or invalid."""
    pass


class GroqAPIError(GroqError):
    """Exception raised when the Groq API call fails."""
    pass


class GroqClientWrapper:
    """
    Wrapper around the official Groq Python SDK with error handling,
    timeout management, and credential protection.
    """

    DECOMMISSIONED_MODELS = {
        "gemma2-9b-it",
        "mixtral-8x7b-32768",
        "llama3-70b-8192",
        "llama3-8b-8192",
        "llama-3.2-1b-preview",
        "llama-3.2-3b-preview",
        "llama-3.2-11b-vision-preview",
        "llama-3.2-90b-vision-preview",
        "deepseek-r1-distill-llama-70b",
        "deepseek-r1-distill-qwen-32b",
        "qwen-2.5-32b",
        "qwen-2.5-coder-32b",
        "qwen-qwq-32b",
        "qwen/qwen3.6-27b",
        "mistral-saba-24b",
    }

    FALLBACK_MODELS = [
        "llama-3.1-8b-instant",
        "openai/gpt-oss-20b",
        "llama-3.3-70b-versatile",
        "openai/gpt-oss-120b",
        "qwen/qwen3.8-27b"
    ]

    def _get_models_to_try(self) -> List[str]:
        """Build an ordered list of active Groq models, filtering out known decommissioned ones."""
        models: List[str] = []
        if self.model and self.model not in self.DECOMMISSIONED_MODELS:
            models.append(self.model)
        for m in self.FALLBACK_MODELS:
            if m not in models and m not in self.DECOMMISSIONED_MODELS:
                models.append(m)
        return models or ["openai/gpt-oss-20b"]

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = settings.GROQ_MODEL,
        temperature: float = settings.GROQ_TEMPERATURE,
        max_tokens: int = settings.GROQ_MAX_TOKENS,
        timeout: float = settings.GROQ_REQUEST_TIMEOUT
    ):
        self.api_key = api_key or settings.GROQ_API_KEY
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client = None
        self._cache: Dict[str, str] = {}
        self._cache_order: List[str] = []
        self._cache_max_size = 150

    def _get_client(self):
        """Get or initialize the official Groq client."""
        if not self.api_key or self.api_key.strip() in ("", "gsk_your_groq_api_key_here"):
            raise GroqConfigurationError(
                "GROQ_API_KEY is not configured. Please set a valid GROQ_API_KEY in your .env file or environment variables."
            )

        if self._client is None:
            try:
                from groq import Groq
                self._client = Groq(api_key=self.api_key, timeout=self.timeout)
            except Exception as e:
                raise GroqConfigurationError(f"Failed to initialize Groq client: {str(e)}") from e

        return self._client

    def generate_chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Send a chat completion request to the Groq API with cache check and fallback models.
        """
        import hashlib
        import json

        # 1. In-memory Cache Check
        try:
            cache_payload = json.dumps({"m": messages, "f": response_format}, sort_keys=True)
            cache_key = hashlib.sha256(cache_payload.encode()).hexdigest()
            if cache_key in self._cache:
                logger.info("Serving Groq response from memory cache.")
                return self._cache[cache_key]
        except Exception:
            cache_key = None

        client = self._get_client()

        models_to_try = self._get_models_to_try()

        last_error = None
        for current_model in models_to_try:
            call_kwargs: Dict[str, Any] = {
                "model": current_model,
                "messages": messages,
                "temperature": self.temperature if temperature is None else temperature,
                "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            }

            if response_format:
                call_kwargs["response_format"] = response_format

            try:
                response = client.chat.completions.create(**call_kwargs)
                choice = response.choices[0]
                content = choice.message.content or ""
                finish_reason = getattr(choice, "finish_reason", "stop")

                # Handle output-token limit (finish_reason == "length") rather than silently truncating
                if finish_reason == "length":
                    logger.warning(f"Groq output reached token limit (finish_reason='length') on {current_model}. Initiating seamless continuation...")
                    continuation_passes = 0
                    while finish_reason == "length" and continuation_passes < 2:
                        continuation_passes += 1
                        continuation_messages = list(messages)
                        continuation_messages.append({"role": "assistant", "content": content})
                        continuation_messages.append({
                            "role": "user",
                            "content": (
                                "Please continue writing the remaining sections of your answer from exactly where you stopped above. "
                                "Do NOT repeat what was already written. Continue seamlessly with the remaining headings, points, and conclusion."
                            )
                        })
                        try:
                            cont_kwargs = dict(call_kwargs)
                            cont_kwargs["messages"] = continuation_messages
                            cont_kwargs["max_tokens"] = min(2048, call_kwargs.get("max_tokens", 2048))
                            cont_resp = client.chat.completions.create(**cont_kwargs)
                            cont_choice = cont_resp.choices[0]
                            cont_text = cont_choice.message.content or ""
                            finish_reason = getattr(cont_choice, "finish_reason", "stop")
                            if cont_text:
                                content = content.rstrip() + "\n\n" + cont_text.lstrip()
                        except Exception as cont_err:
                            logger.warning(f"Continuation pass {continuation_passes} encountered error: {cont_err}")
                            break

                    if finish_reason == "length":
                        # Cleanly close trailing incomplete sentence if truncated
                        last_punct = max(content.rfind("."), content.rfind("!"), content.rfind("?"), content.rfind("\n"))
                        if last_punct > len(content) - 100 and last_punct > 100:
                            content = content[:last_punct + 1]
                        content += "\n\n*(Note: This answer reached maximum output length and covers all core sections from the curriculum passages.)*"

                # Store in cache
                if cache_key and content:
                    if len(self._cache_order) >= self._cache_max_size:
                        oldest = self._cache_order.pop(0)
                        self._cache.pop(oldest, None)
                    self._cache[cache_key] = content
                    self._cache_order.append(cache_key)

                return content

            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e)
                last_error = e

                # Check for decommissioned, deprecated, or not found models
                if "decommissioned" in error_msg.lower() or "not_found" in error_msg.lower() or "model_decommissioned" in error_msg.lower():
                    logger.warning(
                        f"Model {current_model} is decommissioned or unavailable on Groq. Cascading to fallback model..."
                    )
                    continue

                # If rate-limited, log warning and cascade to fallback model
                if "RateLimitError" in error_type or "429" in error_msg or "rate_limit" in error_msg.lower():
                    logger.warning(
                        f"Model {current_model} reached Groq rate limit. Cascading to fallback model if available..."
                    )
                    continue

                if "AuthenticationError" in error_type or "Invalid API Key" in error_msg:
                    raise GroqConfigurationError("Invalid Groq API key. Please check your credentials.") from e

                # For unrecoverable errors on this model, try fallback
                logger.error(f"Groq error with {current_model} [{error_type}]: {error_msg}")
                continue

        # If all models failed
        if last_error:
            error_type = type(last_error).__name__
            error_msg = str(last_error)
            if "RateLimitError" in error_type or "429" in error_msg or "rate_limit" in error_msg.lower():
                raise GroqAPIError("All Groq model rate limits exceeded. Please try again shortly.") from last_error
            raise GroqAPIError(f"Groq generation failed across models: {error_msg}") from last_error

        return ""

    def stream_chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ):
        """
        Stream chat completion tokens in real-time from the Groq API.
        Yields individual token strings as they are generated.
        """
        client = self._get_client()
        models_to_try = self._get_models_to_try()

        for current_model in models_to_try:
            try:
                stream = client.chat.completions.create(
                    model=current_model,
                    messages=messages,
                    temperature=self.temperature if temperature is None else temperature,
                    max_tokens=self.max_tokens if max_tokens is None else max_tokens,
                    stream=True
                )
                yielded_any = False
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta:
                        content = chunk.choices[0].delta.content or ""
                        if content:
                            yield content
                            yielded_any = True
                if yielded_any:
                    return
            except Exception as e:
                error_msg = str(e)
                if "decommissioned" in error_msg.lower() or "not_found" in error_msg.lower() or "model_decommissioned" in error_msg.lower():
                    logger.warning(f"Groq stream model {current_model} decommissioned/unavailable. Cascading to fallback model...")
                elif "429" in error_msg or "rate_limit" in error_msg.lower():
                    logger.warning(f"Groq stream model {current_model} rate limited. Cascading to fallback model...")
                else:
                    logger.warning(f"Groq stream error on {current_model}: {e}")
                continue

