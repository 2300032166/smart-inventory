import os
import json
import logging
from .groq_client_new import call_groq_new

logger = logging.getLogger(__name__)

AI_FAIL_MSG = "AI explanation generation failed"


def load_ai_config() -> dict:
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "data", "ai_config.json")
    try:
        with open(cfg_path) as f:
            return json.load(f)
    except Exception:
        return {}


async def generate_reasoning(prompt: str) -> str:
    """Generate replenishment reasoning via AI.

    Uses Groq Cloud. If it fails for any reason the
    function returns AI_FAIL_MSG.
    """
    cfg = load_ai_config()
    model_name = (
        os.getenv("GROQ_MODEL")
        or os.getenv("CHATBOT_GROQ_MODEL")
        or cfg.get("groq_model")
        or cfg.get("ai_model")
        or "llama-3.1-8b-instant"
    )
    timeout_seconds = float(cfg.get("groq_timeout_seconds", os.getenv("GROQ_TIMEOUT_SECONDS", "15")))
    max_tokens = int(cfg.get("groq_max_tokens", os.getenv("GROQ_MAX_TOKENS", "150")))

    logger.info("[AI] Using provider: Groq | model=%s | timeout=%.1fs", model_name, timeout_seconds)

    try:
        text = await call_groq_new(
            prompt,
            cfg,
            model_name=model_name,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
        )

        if not text:
            logger.error("[AI] Groq returned empty text")
            return AI_FAIL_MSG
        logger.info("[AI] Groq reasoning generated successfully (%d chars)", len(text))
        return text
    except Exception as exc:
        logger.error("[AI] Groq call failed: %s", exc)
        return AI_FAIL_MSG


async def test_connection(provider: str, cfg: dict) -> dict:
    """Test Groq connectivity (used by admin AI-config page)."""
    test_prompt = "Reply with exactly: OK"
    try:
        result = await call_groq_new(test_prompt, cfg)
        return {"status": "connected", "response": result}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
