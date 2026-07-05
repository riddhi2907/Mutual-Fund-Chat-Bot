"""End-to-end RAG chat pipeline: classify → retrieve → generate → validate."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from rag.classifier import (
    ClassificationResult,
    Intent,
    build_performance_response,
    build_refusal_response,
    classify,
    get_scheme_url,
)
from rag.generator import GroqGenerator, GroqGeneratorError
from rag.groq_limits import GroqQuotaExceededError
from rag.retriever import IndexNotReadyError, Retriever, RetrievalResult
from rag.validator import ValidationResult, validate_and_fix

logger = logging.getLogger(__name__)

INSUFFICIENT_CONTEXT_MESSAGE = (
    "I do not have enough information in my indexed Groww sources to answer that question. "
    "Please check the fund page for the latest details."
)


@dataclass(frozen=True)
class ChatResponse:
    type: str
    message: str
    citation_url: str | None = None
    scheme: str | None = None
    last_updated: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type, "message": self.message}
        if self.citation_url:
            payload["citation_url"] = self.citation_url
        if self.scheme:
            payload["scheme"] = self.scheme
        if self.last_updated:
            payload["last_updated"] = self.last_updated
        return payload


class ChatPipeline:
    """Orchestrate classifier, retriever, Groq generator, and validator."""

    def __init__(
        self,
        *,
        retriever: Retriever | None = None,
        generator: GroqGenerator | None = None,
    ) -> None:
        self.retriever = retriever or Retriever()
        self.generator = generator or GroqGenerator()

    def handle(self, message: str) -> ChatResponse:
        classification = classify(message)

        if classification.intent == Intent.PII_DETECTED:
            return ChatResponse(**build_refusal_response(classification.intent))

        if classification.intent in {
            Intent.ADVISORY,
            Intent.COMPARISON,
            Intent.OUT_OF_SCOPE,
        }:
            return ChatResponse(**build_refusal_response(classification.intent))

        if classification.intent == Intent.PERFORMANCE:
            return ChatResponse(**build_performance_response(message))

        retrieval = self.retriever.retrieve(message)
        if not retrieval.sufficient or not retrieval.chunks:
            return self._insufficient_context_response(classification, retrieval)

        try:
            draft = self.generator.generate(
                message,
                retrieval.context,
                retrieval.chunks,
            )
        except GroqQuotaExceededError as exc:
            logger.warning("Groq quota exceeded: %s", exc)
            return self._template_factual_response(retrieval, note=str(exc))
        except GroqGeneratorError as exc:
            logger.error("Groq generation failed: %s", exc)
            return self._template_factual_response(retrieval)

        validated = validate_and_fix(draft, retrieval.chunks)
        if not validated.valid:
            logger.info("Validator fixes applied: %s", validated.fixes_applied)
            if any(
                fix in validated.fixes_applied
                for fix in ("advisory_language_detected", "performance_figures_detected")
            ):
                return self._template_factual_response(retrieval)

        return ChatResponse(
            type="answer",
            message=validated.message,
            citation_url=validated.citation_url,
            scheme=validated.scheme,
            last_updated=validated.last_updated,
        )

    def _insufficient_context_response(
        self,
        classification: ClassificationResult,
        retrieval: RetrievalResult,
    ) -> ChatResponse:
        scheme_name = retrieval.resolved_scheme or classification.resolved_scheme
        citation_url = get_scheme_url(scheme_name) if scheme_name else None
        return ChatResponse(
            type="refusal",
            message=INSUFFICIENT_CONTEXT_MESSAGE,
            citation_url=citation_url,
            scheme=scheme_name,
        )

    def _template_factual_response(
        self,
        retrieval: RetrievalResult,
        *,
        note: str | None = None,
    ) -> ChatResponse:
        """Deterministic fallback that avoids another Groq call."""
        chunk = retrieval.chunks[0]
        citation_url = chunk.source_url.rstrip("/")
        last_updated = chunk.last_fetched_at[:10]
        fact_lines = [line for line in chunk.text.splitlines() if ":" in line]
        fact = fact_lines[-1] if fact_lines else chunk.text
        body = fact if fact.endswith(".") else f"{fact}."
        if note:
            body = f"{body} ({note})"
        message = (
            f"{body}\n\nSource: {citation_url}\n\n"
            f"Last updated from sources: {last_updated}"
        )
        validated = validate_and_fix(message, retrieval.chunks)
        return ChatResponse(
            type="answer",
            message=validated.message,
            citation_url=validated.citation_url,
            scheme=validated.scheme,
            last_updated=validated.last_updated,
        )


_default_pipeline: ChatPipeline | None = None


def get_pipeline() -> ChatPipeline:
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = ChatPipeline()
    return _default_pipeline


def process_message(message: str) -> dict[str, Any]:
    return get_pipeline().handle(message).to_dict()
