import os
import json
import logging
from .gemini_client import call_gemini
from .groq_client import call_groq

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

    AI_PROVIDER can be 'gemini' or 'groq'. If it fails for any reason the
    function returns AI_FAIL_MSG — it never returns a hardcoded explanation.
    """
    cfg = load_ai_config()

    provider = os.getenv("AI_PROVIDER", cfg.get("ai_provider", "groq")).lower()
    logger.info("[AI] Provider resolved to: %s", provider)

    if provider not in ("gemini", "groq"):
        logger.error(
            "[AI] Unsupported provider requested (%s). Supported: groq, gemini",
            provider,
        )
        return AI_FAIL_MSG

    try:
        if provider == "groq":
            text = await call_groq(prompt, cfg)
        else:
            text = await call_gemini(prompt, cfg)

        if not text:
            logger.error("[AI] %s returned empty text", provider.title())
            return AI_FAIL_MSG
        logger.info("[AI] %s reasoning generated successfully (%d chars)", provider.title(), len(text))
        return text
    except Exception as exc:
        logger.error("[AI] %s call failed: %s", provider.title(), exc)
        return AI_FAIL_MSG


async def test_connection(provider: str, cfg: dict) -> dict:
    """Test Gemini connectivity (used by admin AI-config page)."""
    test_prompt = "Reply with exactly: OK"
    try:
        if provider == "gemini":
            result = await call_gemini(test_prompt, cfg)
        elif provider == "groq":
            result = await call_groq(test_prompt, cfg)
        else:
            return {"status": "error", "error": f"Unsupported provider: {provider}"}
        return {"status": "connected", "response": result}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
