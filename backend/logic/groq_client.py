import os
import logging
import asyncio
import time
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from groq import AsyncGroq
except ImportError:  # pragma: no cover
    AsyncGroq = None


async def call_groq(prompt: str, cfg: dict, model_name: Optional[str] = None) -> str:
    """Call Groq using the AsyncGroq API.

    Uses the model name from environment (GROQ_MODEL) or cfg, falling back
    to llama-3.3-70b-versatile. Retries on 429 (rate-limit) with exponential backoff.

    Returns:
        Generated text string.

    Raises:
        ValueError: If API key is missing.
        RuntimeError: If the library is not installed or the call fails.
    """
    api_key = cfg.get("groq_api_key") or os.getenv("GROQ_API_KEY", "")
    model_name = (
        model_name
        or os.getenv("GROQ_MODEL")
        or cfg.get("groq_model")
        or "llama-3.3-70b-versatile"
    )

    if not api_key:
        raise ValueError("No Groq API key configured. Set GROQ_API_KEY in .env")

    if not AsyncGroq:
        raise RuntimeError(
            "groq library is not installed. Run: pip install groq"
        )

    client = AsyncGroq(api_key=api_key)

    logger.info(
        "[Groq] Request | model=%s | prompt_chars=%d",
        model_name,
        len(prompt),
    )
    logger.debug("[Groq] Prompt preview: %.300s", prompt)

    # Retry multiple times on rate-limit (429) with exponential backoff
    for attempt in range(1, 6):
        try:
            response = await client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a clear and direct supply chain advisor. Use simple, professional English. \n\nRULES:\n1. Jump straight into the reasoning. DO NOT include labels like 'The situation can be categorized as...'.\n2. Use specific product units (e.g., 'bottles', 'bags', 'packs'). NEVER use the word 'units'.\n3. Explain the risk (stockout, weather, or delivery) in one or two simple sentences.\n4. Keep it human and professional.\n5. ONLY mention weather if it is significantly impacting demand (multiplier != 1.0x)."},
                    {"role": "user", "content": "Stock 2, Threshold 20, Sales 10, Wait 2, Suggest 97, Weather: No significant impact., Multiplier: 1.0x"},
                    {"role": "assistant", "content": "Milk 1L stock is very low with only 2 bottles left. Order 97 bottles now to meet daily demand and avoid a stockout while waiting for the 2-day delivery."},
                    {"role": "user", "content": "Stock 140, Threshold 40, Sales 13, Wait 5, Suggest 188, Weather: Extreme heat forecast, Multiplier: 1.5x"},
                    {"role": "assistant", "content": "High heat is expected in Vijayawada next week. Reorder 188 packs of Tea Powder now to meet the expected jump in demand."},
                    {"role": "user", "content": prompt}
                ],
                model=model_name,
                temperature=0.5, 
                max_tokens=100,
            )
            text = response.choices[0].message.content
            logger.info(
                "[Groq] Response OK | attempt=%d | chars=%d | preview=%.120s",
                attempt,
                len(text),
                text,
            )
            return text.strip()
        except Exception as exc:
            err = str(exc).lower()
            if ("429" in err or "rate limit" in err) and attempt < 5:
                delay = attempt * 10 # 10s, 20s, 30s, 40s
                logger.warning(
                    "[Groq] Rate-limited (429) on attempt %d, retrying in %ds ...", attempt, delay
                )
                await asyncio.sleep(delay)
                continue
            logger.error("[Groq] FAILED on attempt %d: %s", attempt, exc)
            if attempt < 5:
                await asyncio.sleep(attempt * 2)
                continue
            raise

    raise RuntimeError("Groq call failed after 5 attempts")
