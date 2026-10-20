import logging
import os
from typing import Any, Dict, Generator, List, Optional, Tuple
from config import settings

logger = logging.getLogger(__name__)


class GeminiError(Exception):
    """Base exception for Google Gemini client operations."""
    pass


class GeminiConfigurationError(GeminiError):
    """Exception raised when Gemini API key is missing or invalid."""
    pass


class GeminiAPIError(GeminiError):
    """Exception raised when the Gemini API call fails across candidate models."""
    pass


class GeminiClientWrapper:
    """
    Wrapper around the official Google GenAI Python SDK (google-genai) with
    automatic model fallbacks, message formatting, streaming support, and credential protection.
    """

    FALLBACK_MODELS = [
        "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-flash-latest",
        "gemini-3.8-flash"
    ]

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = settings.GEMINI_MODEL,
        temperature: float = settings.GEMINI_TEMPERATURE,
        max_tokens: int = settings.GEMINI_MAX_TOKENS,
        timeout: float = settings.GEMINI_REQUEST_TIMEOUT
    ):
        self.api_key = api_key if api_key is not None else (settings.GEMINI_API_KEY or os.getenv("GOOGLE_API_KEY", ""))
        self.model = model or "gemini-flash-lite-latest"
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client = None

    def _get_models_to_try(self) -> List[str]:
        """Build an ordered list of candidate Gemini models, starting with the configured model."""
        models: List[str] = []
        if self.model:
            models.append(self.model)
        for m in self.FALLBACK_MODELS:
            if m not in models:
                models.append(m)
        return models or ["gemini-2.0-flash"]

    def _get_client(self):
        """Get or initialize the official Google GenAI client."""
        clean_key = (self.api_key or "").strip()
        if not clean_key or clean_key in ("your_gemini_api_key_here", "gsk_your_groq_api_key_here"):
            raise GeminiConfigurationError(
                "GEMINI_API_KEY (or GOOGLE_API_KEY) is not configured. "
                "Please configure a valid key in your .env or environment variables."
            )

        if self._client is None:
            try:
                import httpx
                from google import genai
                custom_httpx = httpx.Client(
                    timeout=httpx.Timeout(float(self.timeout), connect=30.0)
                )
                self._client = genai.Client(
                    api_key=clean_key,
                    http_options={"httpx_client": custom_httpx}
                )
            except Exception as e:
                raise GeminiConfigurationError(f"Failed to initialize Google GenAI client: {str(e)}") from e

        return self._client

    @staticmethod
    def _convert_messages(messages: List[Dict[str, str]]) -> Tuple[Optional[str], List[Any]]:
        """
        Convert OpenAI-style message dicts to Gemini's system_instruction and Content list.
        Merges consecutive messages of the same role to strictly satisfy Gemini's turn alternation.
        """
        from google.genai import types

        system_parts: List[str] = []
        contents: List[types.Content] = []

        for msg in messages:
            role = (msg.get("role") or "user").strip().lower()
            text = (msg.get("content") or "").strip()
            if not text:
                continue

            if role == "system":
                system_parts.append(text)
            else:
                gemini_role = "model" if role in ("assistant", "model") else "user"
                part = types.Part.from_text(text=text)

                # Merge consecutive turns of identical role
                if contents and contents[-1].role == gemini_role:
                    contents[-1].parts.append(part)
                else:
                    contents.append(types.Content(role=gemini_role, parts=[part]))

        system_instruction = "\n\n".join(system_parts).strip() or None

        if not contents:
            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_text(text="Please proceed with the requested clinical answer.")]
            ))

        return system_instruction, contents

    def generate_chat_completion(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        response_format: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate a non-streaming chat completion with automatic model fallback.
        """
        from google.genai import types

        client = self._get_client()
        system_instruction, contents = self._convert_messages(messages)

        config_kwargs: Dict[str, Any] = {
            "temperature": temperature if temperature is not None else self.temperature,
            "max_output_tokens": max_tokens if max_tokens is not None else self.max_tokens,
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction

        if response_format and response_format.get("type") in ("json_object", "json"):
            config_kwargs["response_mime_type"] = "application/json"

        config = types.GenerateContentConfig(**config_kwargs)

        models_to_try = self._get_models_to_try()
        last_error = None

        for model_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
                if response and response.text:
                    return response.text
                elif response and response.candidates:
                    # Fallback extraction from candidates
                    candidate = response.candidates[0]
                    parts_text = []
                    if candidate.content and candidate.content.parts:
                        for p in candidate.content.parts:
                            if hasattr(p, "text") and p.text:
                                parts_text.append(p.text)
                    if parts_text:
                        return "".join(parts_text)
            except Exception as e:
                last_error = e
                logger.warning(f"Gemini generation error with model '{model_name}': {e}. Trying fallback if available.")
                continue

        error_msg = f"Gemini generation failed across models {models_to_try}: {last_error}"
        logger.error(error_msg)
        raise GeminiAPIError(error_msg) from last_error

    def stream_chat_completion(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ) -> Generator[str, None, None]:
        """
        Stream tokens in real-time with model fallback on early failure.
        """
        from google.genai import types

        client = self._get_client()
        system_instruction, contents = self._convert_messages(messages)

        config_kwargs: Dict[str, Any] = {
            "temperature": temperature if temperature is not None else self.temperature,
            "max_output_tokens": max_tokens if max_tokens is not None else self.max_tokens,
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction

        config = types.GenerateContentConfig(**config_kwargs)

        models_to_try = self._get_models_to_try()
        last_error = None

        for model_name in models_to_try:
            tokens_emitted = 0
            try:
                response_stream = client.models.generate_content_stream(
                    model=model_name,
                    contents=contents,
                    config=config
                )
                for chunk in response_stream:
                    if chunk.text:
                        tokens_emitted += 1
                        yield chunk.text
                if tokens_emitted > 0:
                    return
            except Exception as e:
                last_error = e
                logger.warning(f"Gemini streaming error with model '{model_name}': {e}.")
                # If error occurred after yielding tokens, stop to avoid mixed responses
                if tokens_emitted > 0:
                    return
                # If zero tokens were emitted, try next fallback model
                continue

        error_msg = f"Gemini streaming failed across models {models_to_try}: {last_error}"
        logger.error(error_msg)
        raise GeminiAPIError(error_msg) from last_error

