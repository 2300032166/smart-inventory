import httpx
import os
import json
from .gemini_client import call_gemini


def load_ai_config():
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "data", "ai_config.json")
    try:
        with open(cfg_path) as f:
            return json.load(f)
    except Exception:
        return {}


async def call_ollama(prompt: str, cfg: dict) -> str:
    ollama_url = cfg.get("ollama_url") or os.getenv("OLLAMA_URL", "http://localhost:11434")
    model = cfg.get("ollama_model") or os.getenv("OLLAMA_MODEL", "llama3")

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{ollama_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "").strip()


async def generate_reasoning(prompt: str) -> str:
    cfg = load_ai_config()
    provider = cfg.get("ai_provider") or os.getenv("AI_PROVIDER", "gemini")

    if provider == "gemini":
        try:
            gen = await call_gemini(prompt, cfg)
            if gen:
                return gen
            # treat None as failure and fallthrough to Ollama
        except Exception as gem_err:
            print(f"[AI] Gemini failed: {gem_err}. Falling back to Ollama.")

    # Try Ollama (local) as a fallback if configured
    try:
        return await call_ollama(prompt, cfg)
    except Exception as ollama_err:
        print(f"[AI] Ollama failed: {ollama_err}. Using fallback reasoning.")
        return _fallback_reasoning()


def _fallback_reasoning() -> str:
    return (
        "Based on current stock levels and historical sales patterns, this product "
        "requires replenishment before the supplier lead time is exceeded. "
        "Order now to avoid a potential stockout and ensure continuous availability for customers."
    )


async def test_connection(provider: str, cfg: dict) -> dict:
    test_prompt = "Reply with exactly: OK"
    try:
        if provider == "gemini":
            result = await call_gemini(test_prompt, cfg)
        else:
            result = await call_ollama(test_prompt, cfg)
        return {"status": "connected", "response": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}
