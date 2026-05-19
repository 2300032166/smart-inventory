import os
import json
import asyncio
from typing import Optional

try:
    import google.generativeai as genai
except Exception:  # pragma: no cover - library may be missing in test env
    genai = None


def _configure(api_key: str):
    if not genai:
        return False
    genai.configure(api_key=api_key)
    return True


async def call_gemini(prompt: str, cfg: dict, model: Optional[str] = None) -> Optional[str]:
    """Call Google Gemini via google-generativeai.

    Returns the generated text on success, or None on failure.
    """
    api_key = cfg.get("gemini_api_key") or os.getenv("GEMINI_API_KEY", "")
    model = model or cfg.get("gemini_model") or os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    if not api_key:
        raise ValueError("No valid Gemini API key configured")

    if not genai:
        raise RuntimeError("google-generativeai library is not installed")

    # Configure client (idempotent)
    _configure(api_key)

    # The official client is synchronous; run in a thread to avoid blocking.
    def _generate():
        # Keep prompt compact and tokens limited for free-tier friendliness
        try:
            resp = genai.generate(
                model=model,
                prompt=prompt,
                temperature=0.2,
                max_output_tokens=256,
            )
            # Response may include different shapes across versions.
            if hasattr(resp, "text") and resp.text:
                return resp.text
            # Older shapes use 'candidates'
            data = getattr(resp, "candidates", None) or resp
            if isinstance(data, (list,)) and data:
                first = data[0]
                return first.get("content") or first.get("text") or str(first)
            # Fallback to string conversion
            return str(resp)
        except Exception as e:
            raise

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Run in a thread to avoid blocking the event loop
            text = await asyncio.to_thread(_generate)
        else:
            text = _generate()
        # Ensure JSON-safe string
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="ignore")
        return (text or "").strip()
    except Exception:
        return None
