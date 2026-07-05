"""Client-side Groq quota tracking for llama-3.3-70b-versatile free-tier limits."""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass

DEFAULT_REQUESTS_PER_MINUTE = 30
DEFAULT_REQUESTS_PER_DAY = 1_000
DEFAULT_TOKENS_PER_MINUTE = 12_000
DEFAULT_TOKENS_PER_DAY = 100_000
DEFAULT_MAX_OUTPUT_TOKENS = 256
WINDOW_SECONDS = 60
DAY_SECONDS = 86_400


class GroqQuotaExceededError(Exception):
    """Raised when a Groq call would exceed configured rate or token limits."""


@dataclass(frozen=True)
class GroqLimits:
    requests_per_minute: int
    requests_per_day: int
    tokens_per_minute: int
    tokens_per_day: int
    max_output_tokens: int


def load_groq_limits() -> GroqLimits:
    return GroqLimits(
        requests_per_minute=int(
            os.getenv("GROQ_MAX_REQUESTS_PER_MINUTE", DEFAULT_REQUESTS_PER_MINUTE)
        ),
        requests_per_day=int(
            os.getenv("GROQ_MAX_REQUESTS_PER_DAY", DEFAULT_REQUESTS_PER_DAY)
        ),
        tokens_per_minute=int(
            os.getenv("GROQ_MAX_TOKENS_PER_MINUTE", DEFAULT_TOKENS_PER_MINUTE)
        ),
        tokens_per_day=int(
            os.getenv("GROQ_MAX_TOKENS_PER_DAY", DEFAULT_TOKENS_PER_DAY)
        ),
        max_output_tokens=int(
            os.getenv("GROQ_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS)
        ),
    )


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 characters per token)."""
    return max(1, len(text) // 4)


class GroqRateLimiter:
    """
    Track Groq usage in-process to stay within RPM/RPD/TPM/TPD limits.

  Defaults match llama-3.3-70b-versatile on Groq free tier.
    """

    def __init__(self, limits: GroqLimits | None = None) -> None:
        self.limits = limits or load_groq_limits()
        self._lock = threading.Lock()
        self._request_times: deque[float] = deque()
        self._token_events: deque[tuple[float, int]] = deque()
        self._daily_request_times: deque[float] = deque()
        self._daily_token_events: deque[tuple[float, int]] = deque()

    def _prune(self, now: float) -> None:
        minute_cutoff = now - WINDOW_SECONDS
        day_cutoff = now - DAY_SECONDS
        while self._request_times and self._request_times[0] < minute_cutoff:
            self._request_times.popleft()
        while self._token_events and self._token_events[0][0] < minute_cutoff:
            self._token_events.popleft()
        while self._daily_request_times and self._daily_request_times[0] < day_cutoff:
            self._daily_request_times.popleft()
        while self._daily_token_events and self._daily_token_events[0][0] < day_cutoff:
            self._daily_token_events.popleft()

    def _minute_tokens(self) -> int:
        return sum(tokens for _, tokens in self._token_events)

    def _daily_tokens(self) -> int:
        return sum(tokens for _, tokens in self._daily_token_events)

    def check(self, estimated_tokens: int) -> None:
        """Fail fast before calling Groq if limits would be exceeded."""
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            if len(self._request_times) >= self.limits.requests_per_minute:
                raise GroqQuotaExceededError(
                    f"Groq request limit reached ({self.limits.requests_per_minute}/min). "
                    "Please try again shortly."
                )
            if len(self._daily_request_times) >= self.limits.requests_per_day:
                raise GroqQuotaExceededError(
                    f"Groq daily request limit reached ({self.limits.requests_per_day}/day)."
                )
            projected_minute = self._minute_tokens() + estimated_tokens
            if projected_minute > self.limits.tokens_per_minute:
                raise GroqQuotaExceededError(
                    f"Groq token limit would be exceeded ({self.limits.tokens_per_minute}/min)."
                )
            projected_daily = self._daily_tokens() + estimated_tokens
            if projected_daily > self.limits.tokens_per_day:
                raise GroqQuotaExceededError(
                    f"Groq daily token limit would be exceeded ({self.limits.tokens_per_day}/day)."
                )

    def record(self, total_tokens: int) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            self._request_times.append(now)
            self._daily_request_times.append(now)
            self._token_events.append((now, total_tokens))
            self._daily_token_events.append((now, total_tokens))


_default_limiter: GroqRateLimiter | None = None


def get_groq_rate_limiter() -> GroqRateLimiter:
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = GroqRateLimiter()
    return _default_limiter
