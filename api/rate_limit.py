"""Simple per-IP request throttling for the chat API."""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

DEFAULT_CHAT_REQUESTS_PER_MINUTE = 25


class RateLimitExceededError(Exception):
    """Raised when a client exceeds the chat endpoint rate limit."""


class ChatRateLimiter:
    """In-memory per-IP sliding window limiter (MVP)."""

    def __init__(self, requests_per_minute: int | None = None) -> None:
        self.requests_per_minute = requests_per_minute or int(
            os.getenv("CHAT_REQUESTS_PER_MINUTE", DEFAULT_CHAT_REQUESTS_PER_MINUTE)
        )
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, client_key: str) -> None:
        with self._lock:
            now = time.monotonic()
            window = self._events[client_key]
            cutoff = now - 60
            while window and window[0] < cutoff:
                window.popleft()
            if len(window) >= self.requests_per_minute:
                raise RateLimitExceededError(
                    f"Too many requests. Limit is {self.requests_per_minute} per minute."
                )
            window.append(now)


_default_chat_limiter: ChatRateLimiter | None = None


def get_chat_rate_limiter() -> ChatRateLimiter:
    global _default_chat_limiter
    if _default_chat_limiter is None:
        _default_chat_limiter = ChatRateLimiter()
    return _default_chat_limiter
