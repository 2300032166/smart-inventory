import os
import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import google.generativeai as genai
except ImportError:  # pragma: no cover
    genai = None


def _configure(api_key: str) -> bool:
    if not genai:
        return False
    genai.configure(api_key=api_key)
    return True


async def call_gemini(prompt: str, cfg: dict, model_name: Optional[str] = None) -> str:
    """Call Google Gemini using the GenerativeModel API.

    Uses the model name from environment (GEMINI_MODEL) or cfg, falling back
    to gemini-2.5-flash-lite.  Retries once on 429 (rate-limit) after a short
    delay before raising.

    Returns:
        Generated text string.

    Raises:
        ValueError: If API key is missing.
        RuntimeError: If the library is not installed or the call fails.
    """
    api_key = cfg.get("gemini_api_key") or os.getenv("GEMINI_API_KEY", "")
    model_name = (
        model_name
        or os.getenv("GEMINI_MODEL")
        or cfg.get("gemini_model")
        or "gemini-2.5-flash-lite"
    )

    # Auto-upgrade deprecated 1.5 models to 2.5-flash-lite to prevent 404s
    if "1.5-flash" in model_name:
        logger.warning("[Gemini] Auto-upgrading deprecated model %s to gemini-2.5-flash-lite", model_name)
        model_name = "gemini-2.5-flash-lite"

    if not api_key:
        raise ValueError("No Gemini API key configured. Set GEMINI_API_KEY in .env")

    if not genai:
        raise RuntimeError(
            "google-generativeai library is not installed. Run: pip install google-generativeai"
        )

    _configure(api_key)

    def _generate() -> str:
        logger.info(
            "[Gemini] Request | model=%s | prompt_chars=%d",
            model_name,
            len(prompt),
        )
        logger.debug("[Gemini] Prompt preview: %.300s", prompt)

        model = genai.GenerativeModel(model_name)

        # Retry multiple times on rate-limit (429) with exponential backoff
        for attempt in range(1, 4):
            try:
                response = model.generate_content(prompt)
                text = response.text
                logger.info(
                    "[Gemini] Response OK | attempt=%d | chars=%d | preview=%.120s",
                    attempt,
                    len(text),
                    text,
                )
                return text
            except Exception as exc:
                err = str(exc)
                if ("429" in err or "quota" in err.lower()) and attempt < 3:
                    delay = attempt * 5
                    logger.warning(
                        "[Gemini] Rate-limited (429) on attempt %d, retrying in %ds ...", attempt, delay
                    )
                    time.sleep(delay)
                    continue
                logger.error("[Gemini] FAILED on attempt %d: %s", attempt, exc)
                raise

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Offload blocking SDK call so FastAPI stays async
            text = await asyncio.to_thread(_generate)
        else:
            text = _generate()

        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="ignore")

        result = (text or "").strip()
        if not result:
            raise RuntimeError("Gemini returned an empty response")
        return result

    except Exception as exc:
        logger.error("[Gemini] call_gemini FAILED: %s", exc)
        raise
