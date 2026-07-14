import os
import json
import logging
import asyncio
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

try:
    from groq import AsyncGroq
except ImportError:
    AsyncGroq = None

class ChatbotGroqClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("CHATBOT_GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
        self.client = None
        if AsyncGroq and self.api_key:
            self.client = AsyncGroq(api_key=self.api_key)

    async def stream_chat(self, messages: List[Dict[str, str]], model: str = "llama-3.3-70b-versatile"):
        if not self.client:
            logger.error("[ChatbotGroq] Client not initialized. Check API key and 'groq' package.")
            yield "⛔ Groq AI client not configured. Please set CHATBOT_GROQ_API_KEY."
            return

        try:
            stream = await self.client.chat.completions.create(
                messages=messages,
                model=model,
                temperature=0.6,
                max_tokens=700,
                stream=True,
            )
            async for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
        except Exception as e:
            err_str = str(e)
            logger.error(f"[ChatbotGroq] Stream Error: {err_str}")
            if "429" in err_str or "rate_limit" in err_str.lower() or "rate limit" in err_str.lower():
                yield "⏳ I'm getting a lot of questions right now and hit the free-tier rate limit. Please wait a few seconds and try again."
            else:
                yield f"⚠️ AI error: {err_str}"
