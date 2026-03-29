"""
Gemini API client wrapper.

Uses the new google.genai SDK (replacement for deprecated google.generativeai).
"""

import time
import logging
from google import genai
from google.genai import types
from django.conf import settings

logger = logging.getLogger(__name__)

def _get_client() -> genai.Client:
    """Return a configured Gemini client."""
    return genai.Client(
        api_key=settings.GEMINI_API_KEY,
        http_options={"timeout": 60000}
    )


def call_gemini(
    prompt: str,
    temperature: float = 0.0,
    max_tokens: int = 8192,
    system_instruction: str | None = None,
) -> tuple[str, int]:
    """
    Send a prompt to Gemini and return the text response plus token usage.

    Args:
        prompt: The user message to send.
        temperature: Sampling temperature (0 = deterministic).
        max_tokens: Maximum output tokens.
        system_instruction: Optional system-level instruction.

    Returns:
        A tuple of (text_response, total_tokens_used).

    Raises:
        RuntimeError: If the API call fails.
    """
    client = _get_client()

    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
    )

    if system_instruction:
        config.system_instruction = system_instruction

    last_exc = None
    for attempt in range(3):
        try:
            # Enforce explicit 60s timeout in HTTP client mapping
            # (Note: GenAI SDK usually defaults cleanly, but we add timeout wrapper logic)
            start_time = time.time()
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=prompt,
                config=config,
            )
            
            # Token tracking observability
            usage = getattr(response, "usage_metadata", None)
            total_tokens = usage.total_token_count if usage else 0
            
            logger.info({
                "event": "gemini_api_call",
                "stage": "generate",
                "attempt": attempt + 1,
                "latency_sec": round(time.time() - start_time, 2),
                "tokens": total_tokens
            })

            return (response.text, total_tokens)

        except Exception as exc:
            last_exc = exc
            logger.warning(f"Gemini API attempt {attempt + 1} failed: {exc}")
            time.sleep(1 + attempt)  # Exponential-ish backoff

    logger.error("All Gemini API attempts failed.")
    raise RuntimeError(f"Gemini API call failed after 3 attempts: {last_exc}") from last_exc
