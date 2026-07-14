"""
Manages one or more Groq API keys for the Daily Brief AI reasoning calls.

Why this exists
----------------
The free Groq tier enforces a per-key requests-per-minute (RPM) limit. The
Daily Brief needs an AI explanation for up to ~100 products, so a single key
runs out of headroom quickly and the remaining products silently keep their
fallback text forever (they never get retried once the background task's
gather() call finishes).

This module lets the app be configured with a primary key plus one or more
backup keys (GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEY_3, ...). Requests are
spread across all configured keys, and any key that gets rate-limited (HTTP
429) is put on a short cooldown while the others keep serving traffic, so the
brief can still finish quickly instead of stalling entirely on one exhausted
key.
"""

import os
import time
import logging
import itertools
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class _KeyState:
    key: str
    label: str
    cooldown_until: float = 0.0
    # Sliding window of recent call timestamps, used to spread load across keys.
    recent_calls: List[float] = field(default_factory=list)

    def is_cooling_down(self, now: float) -> bool:
        return now < self.cooldown_until

    def record_call(self, now: float):
        self.recent_calls.append(now)
        # Keep only the last 60s of history.
        cutoff = now - 60
        self.recent_calls = [t for t in self.recent_calls if t >= cutoff]

    def load_last_minute(self, now: float) -> int:
        cutoff = now - 60
        return sum(1 for t in self.recent_calls if t >= cutoff)


class GroqKeyManager:
    """Round-robins Groq API keys and tracks per-key rate-limit cooldowns."""

    def __init__(self):
        self._keys: List[_KeyState] = []
        self._cursor = 0
        self._load_keys()

    def _load_keys(self):
        collected: List[tuple] = []

        primary = os.getenv("GROQ_API_KEY", "").strip()
        if primary:
            collected.append((primary, "GROQ_API_KEY"))

        # Support GROQ_API_KEY_2, GROQ_API_KEY_3, ... for as many backups as configured.
        idx = 2
        while True:
            val = os.getenv(f"GROQ_API_KEY_{idx}", "").strip()
            if not val:
                break
            collected.append((val, f"GROQ_API_KEY_{idx}"))
            idx += 1

        # De-duplicate in case the same value was set twice.
        seen = set()
        for key, label in collected:
            if key in seen:
                continue
            seen.add(key)
            self._keys.append(_KeyState(key=key, label=label))

        if self._keys:
            logger.info(
                "[GroqKeyManager] Loaded %d Groq API key(s): %s",
                len(self._keys),
                ", ".join(k.label for k in self._keys),
            )
        else:
            logger.warning("[GroqKeyManager] No GROQ_API_KEY configured.")

    def reload(self):
        """Re-read keys from the environment (used after admin config changes)."""
        self._keys = []
        self._cursor = 0
        self._load_keys()

    @property
    def key_count(self) -> int:
        return len(self._keys)

    def has_keys(self) -> bool:
        return bool(self._keys)

    def all_keys_for_retry(self) -> List[str]:
        """Return every configured key, ordered starting from the least-loaded /
        least-recently-cooling-down one, for a caller that wants to try each key
        in turn until one succeeds."""
        now = time.time()
        if not self._keys:
            return []
        ordered = sorted(
            self._keys,
            key=lambda k: (k.is_cooling_down(now), k.cooldown_until, k.load_last_minute(now)),
        )
        return [k.key for k in ordered]

    def pick_key(self) -> Optional[str]:
        """Pick the best available key: prefer one that isn't cooling down and
        has the lowest recent load (simple round-robin + load awareness)."""
        if not self._keys:
            return None
        now = time.time()
        available = [k for k in self._keys if not k.is_cooling_down(now)]
        pool = available or self._keys  # if all cooling down, still try the one closest to recovering
        pool = sorted(pool, key=lambda k: (k.cooldown_until, k.load_last_minute(now)))
        chosen = pool[0]
        chosen.record_call(now)
        return chosen.key

    def mark_rate_limited(self, key: str, cooldown_seconds: float = 20.0):
        for k in self._keys:
            if k.key == key:
                k.cooldown_until = time.time() + cooldown_seconds
                logger.warning(
                    "[GroqKeyManager] %s rate-limited, cooling down for %.0fs.",
                    k.label,
                    cooldown_seconds,
                )
                return

    def seconds_until_any_key_ready(self) -> float:
        if not self._keys:
            return 0.0
        now = time.time()
        return max(0.0, min(k.cooldown_until for k in self._keys) - now)


# Module-level singleton — shared across all Daily Brief AI calls in this process.
key_manager = GroqKeyManager()
