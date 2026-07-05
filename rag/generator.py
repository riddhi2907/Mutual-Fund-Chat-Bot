"""Groq LLM generator with constrained system prompt for factual answers."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from dotenv import load_dotenv
from groq import APIStatusError, Groq

from rag.groq_limits import (
    GroqQuotaExceededError,
    estimate_tokens,
    get_groq_rate_limiter,
    load_groq_limits,
)
from rag.retriever import RetrievedChunk

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
MAX_GROQ_RETRIES = 2
GROQ_TIMEOUT_SECONDS = 30

SYSTEM_PROMPT = """You are a facts-only HDFC Mutual Fund FAQ assistant.

Rules:
1. Answer ONLY using the provided context chunks. Do not invent facts.
2. Write at most 3 sentences in the answer body (excluding Source line and footer).
3. Include exactly one Source line with exactly one groww.in URL copied from the context.
4. Do not give investment advice, opinions, recommendations, or return calculations.
5. If context is insufficient, say you do not have enough information and still include one relevant groww.in URL from the context.
6. End with a footer line: Last updated from sources: YYYY-MM-DD (use the newest date from context metadata when available).

Format:
<answer sentences>

Source: <single groww.in URL>

Last updated from sources: <date>
"""


class GroqGeneratorError(Exception):
    """Raised when Groq generation fails after retries."""


def get_groq_model() -> str:
    return os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)


def get_groq_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise GroqGeneratorError("GROQ_API_KEY is not configured")
    return Groq(api_key=api_key, timeout=GROQ_TIMEOUT_SECONDS)


def _build_user_prompt(query: str, context: str, chunks: tuple[RetrievedChunk, ...]) -> str:
    dates = sorted({chunk.last_fetched_at for chunk in chunks})
    newest_date = dates[-1][:10] if dates else "unknown"
    return (
        f"User question: {query}\n\n"
        f"Context chunks:\n{context}\n\n"
        f"Newest source fetch date in context: {newest_date}\n"
        "Write the answer now."
    )


def _extract_total_tokens(response: Any) -> int:
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0
    total = getattr(usage, "total_tokens", None)
    if total is not None:
        return int(total)
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    return prompt + completion


class GroqGenerator:
    """Call Groq chat completions with quota checks and 429 retries."""

    def __init__(
        self,
        *,
        client: Groq | None = None,
        model: str | None = None,
        rate_limiter: Any | None = None,
    ) -> None:
        self._client = client
        self.model = model or get_groq_model()
        self.rate_limiter = rate_limiter or get_groq_rate_limiter()
        self.limits = load_groq_limits()

    @property
    def client(self) -> Groq:
        if self._client is None:
            self._client = get_groq_client()
        return self._client

    def generate(
        self,
        query: str,
        context: str,
        chunks: tuple[RetrievedChunk, ...],
    ) -> str:
        if not context.strip():
            raise GroqGeneratorError("Cannot generate without retrieved context")

        user_prompt = _build_user_prompt(query, context, chunks)
        estimated = estimate_tokens(SYSTEM_PROMPT + user_prompt) + self.limits.max_output_tokens
        self.rate_limiter.check(estimated)

        last_error: Exception | None = None
        for attempt in range(MAX_GROQ_RETRIES + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0,
                    max_tokens=self.limits.max_output_tokens,
                )
                message = response.choices[0].message.content
                if not message or not message.strip():
                    raise GroqGeneratorError("Groq returned an empty response")
                total_tokens = _extract_total_tokens(response)
                if total_tokens <= 0:
                    total_tokens = estimated
                self.rate_limiter.record(total_tokens)
                return message.strip()
            except GroqQuotaExceededError:
                raise
            except APIStatusError as exc:
                last_error = exc
                if exc.status_code == 429 and attempt < MAX_GROQ_RETRIES:
                    sleep_seconds = 2**attempt
                    logger.warning(
                        "Groq rate limited (429); retrying in %ss", sleep_seconds
                    )
                    time.sleep(sleep_seconds)
                    continue
                break
            except Exception as exc:
                last_error = exc
                break

        raise GroqGeneratorError(f"Groq generation failed: {last_error}") from last_error


def generate_answer(
    query: str,
    context: str,
    chunks: tuple[RetrievedChunk, ...],
    *,
    generator: GroqGenerator | None = None,
) -> str:
    return (generator or GroqGenerator()).generate(query, context, chunks)
