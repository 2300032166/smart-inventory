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
    for attempt in range(1, 4):
        try:
            response = await client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a helpful store advisor. Explain the situation in 2-3 natural, easy-to-understand sentences. Use simple English only. Avoid technical terms like 'lead time', 'replenish', or 'inventory'. Just tell the manager what is happening and why the order is needed."},
                    {"role": "user", "content": "Milk 1L: 0.2 days left, 2 days wait. Buy 97."},
                    {"role": "assistant", "content": "We only have enough milk to last for half a day, and the new delivery will take 2 days to get here. You should order 97 bottles now so we don't run out of stock while waiting for the shipment."},
                    {"role": "user", "content": "Salt 1kg: 1.7 days left, 4 days wait. Buy 109."},
                    {"role": "assistant", "content": "The salt will run out in less than 2 days, but it takes 4 days for the supplier to bring more. Ordering 109 packs today will help keep the shelves full until the new stock arrives."},
                    {"role": "user", "content": prompt}
                ],
                model=model_name,
                temperature=0.5, # More natural flow
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
            err = str(exc)
            if ("429" in err or "rate limit" in err.lower()) and attempt < 3:
                delay = attempt * 5
                logger.warning(
                    "[Groq] Rate-limited (429) on attempt %d, retrying in %ds ...", attempt, delay
                )
                await asyncio.sleep(delay)
                continue
            logger.error("[Groq] FAILED on attempt %d: %s", attempt, exc)
            raise

    raise RuntimeError("Groq call failed after 3 attempts")
