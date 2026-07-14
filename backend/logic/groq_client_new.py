import os
import logging
import asyncio
import itertools
from typing import Optional

from .groq_key_manager import key_manager

logger = logging.getLogger(__name__)

try:
    from groq import AsyncGroq
except ImportError:
    AsyncGroq = None

# One AsyncGroq client per API key, reused across calls instead of
# reconnecting every time.
_clients_by_key: dict = {}


def _client_for(api_key: str):
    client = _clients_by_key.get(api_key)
    if client is None:
        client = AsyncGroq(api_key=api_key)
        _clients_by_key[api_key] = client
    return client


async def call_groq_new(
    prompt: str,
    cfg: dict,
    model_name: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    model_name = (
        model_name
        or os.getenv("GROQ_MODEL")
        or os.getenv("CHATBOT_GROQ_MODEL")
        or cfg.get("groq_model")
        or cfg.get("ai_model")
        or "llama-3.1-8b-instant"
    )
    timeout_seconds = timeout_seconds or float(cfg.get("groq_timeout_seconds", os.getenv("GROQ_TIMEOUT_SECONDS", "4")))
    max_tokens = max_tokens or int(cfg.get("groq_max_tokens", os.getenv("GROQ_MAX_TOKENS", "40")))
    temperature = float(cfg.get("groq_temperature", os.getenv("GROQ_TEMPERATURE", "0.7")))

    if not AsyncGroq:
        raise RuntimeError("groq not installed")

    # Explicit single key passed via cfg (e.g. admin "test connection" flow) bypasses
    # the key manager entirely.
    forced_key = cfg.get("groq_api_key")
    if forced_key:
        keys_to_try = [forced_key]
    else:
        if not key_manager.has_keys():
            raise ValueError("No Groq API key configured. Set GROQ_API_KEY (and optionally GROQ_API_KEY_2) in secrets.")
        # Try every configured key before giving up — a product should only fall
        # back to the static explanation if ALL keys are exhausted/failing.
        keys_to_try = key_manager.all_keys_for_retry()

    last_exc: Optional[Exception] = None

    retry_rounds = max(2, len(keys_to_try))
    for round_num, api_key in enumerate(itertools.islice(itertools.cycle(keys_to_try), retry_rounds), start=1):
        client = _client_for(api_key)
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": "You are a professional supply chain advisor. Use simple English. Keep replies brief and direct. Vary your wording and sentence structure for each item. Never use labels like 'Stock Risk'. Never use the word 'units'. Do not reuse the same template or opening phrase."},
                        {"role": "user", "content": prompt},
                    ],
                    model=model_name,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    frequency_penalty=0.2,
                    presence_penalty=0.2,
                ),
                timeout=timeout_seconds,
            )
            content = response.choices[0].message.content.strip()
            return content or ""
        except asyncio.TimeoutError as exc:
            last_exc = exc
            logger.warning("[AI] Groq timed out after %.1fs (round %d, key=%s)", timeout_seconds, round_num, _key_label(api_key))
            continue
        except Exception as exc:
            last_exc = exc
            err = str(exc).lower()
            if "429" in err or "rate limit" in err or "too many requests" in err:
                if not forced_key:
                    key_manager.mark_rate_limited(api_key)
                logger.warning("[AI] Rate limited on key=%s (round %d) — switching key.", _key_label(api_key), round_num)
                await asyncio.sleep(0.5)
                continue
            logger.warning("[AI] Groq call failed on key=%s (round %d): %s", _key_label(api_key), round_num, exc)
            await asyncio.sleep(0.3)
            continue

    logger.error("[AI] Groq failed after trying all configured key(s): %s", last_exc)
    raise last_exc or RuntimeError("Groq call failed")


def _key_label(api_key: str) -> str:
    return f"...{api_key[-4:]}" if api_key and len(api_key) > 4 else "unknown"
