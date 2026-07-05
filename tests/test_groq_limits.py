"""Tests for Groq client-side quota guardrails."""

from __future__ import annotations

import pytest

from rag.groq_limits import GroqLimits, GroqQuotaExceededError, GroqRateLimiter, estimate_tokens


def test_estimate_tokens_minimum() -> None:
    assert estimate_tokens("hi") == 1


def test_token_per_minute_limit() -> None:
    limiter = GroqRateLimiter(
        limits=GroqLimits(
            requests_per_minute=30,
            requests_per_day=1000,
            tokens_per_minute=100,
            tokens_per_day=10000,
            max_output_tokens=64,
        )
    )
    limiter.check(80)
    limiter.record(80)
    with pytest.raises(GroqQuotaExceededError, match="token limit"):
        limiter.check(30)


def test_daily_request_limit() -> None:
    limiter = GroqRateLimiter(
        limits=GroqLimits(
            requests_per_minute=100,
            requests_per_day=1,
            tokens_per_minute=12000,
            tokens_per_day=100000,
            max_output_tokens=64,
        )
    )
    limiter.check(10)
    limiter.record(10)
    with pytest.raises(GroqQuotaExceededError, match="daily request"):
        limiter.check(10)
