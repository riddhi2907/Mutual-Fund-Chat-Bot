"""API and pipeline tests for Phase 3."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from rag.classifier import Intent
from rag.pipeline import ChatPipeline
from rag.retriever import RetrievedChunk


@pytest.fixture
def sample_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="hdfc-mid-cap-fund-direct-growth-expense_ratio-001",
        text=(
            "Fund: HDFC Mid Cap Fund Direct Growth\n"
            "Category: Equity — Mid Cap\n"
            "Expense ratio: 0.75%"
        ),
        score=0.9,
        scheme_name="HDFC Mid Cap Fund Direct Growth",
        scheme_category="Equity — Mid Cap",
        section="expense_ratio",
        content_type="factual",
        source_url="https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
        last_fetched_at="2026-07-05T17:10:32Z",
    )


def test_pipeline_refusal_skips_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    generator = MagicMock()
    retriever = MagicMock()
    pipeline = ChatPipeline(retriever=retriever, generator=generator)

    response = pipeline.handle("Should I invest in HDFC Small Cap?")

    assert response.type == "refusal"
    retriever.retrieve.assert_not_called()
    generator.generate.assert_not_called()


def test_pipeline_performance_skips_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    generator = MagicMock()
    retriever = MagicMock()
    pipeline = ChatPipeline(retriever=retriever, generator=generator)

    response = pipeline.handle("3-year return of HDFC Gold ETF FoF?")

    assert response.type == "scheme_link"
    assert response.citation_url
    generator.generate.assert_not_called()


def test_pipeline_factual_uses_validator(
    sample_chunk: RetrievedChunk,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rag import retriever as retriever_module

    retrieval = retriever_module.RetrievalResult(
        query="expense ratio mid cap",
        resolved_scheme=sample_chunk.scheme_name,
        chunks=(sample_chunk,),
        context=sample_chunk.text,
        sufficient=True,
    )
    retriever = MagicMock()
    retriever.retrieve.return_value = retrieval
    generator = MagicMock()
    generator.generate.return_value = (
        "The expense ratio is 0.75%.\n\n"
        "Source: https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth\n\n"
        "Last updated from sources: 2026-07-05"
    )
    pipeline = ChatPipeline(retriever=retriever, generator=generator)

    response = pipeline.handle("What is the expense ratio of HDFC Mid Cap?")

    assert response.type == "answer"
    assert response.scheme == sample_chunk.scheme_name
    generator.generate.assert_called_once()


def test_groq_rate_limiter_blocks_excess_requests() -> None:
    from rag.groq_limits import GroqLimits, GroqQuotaExceededError, GroqRateLimiter

    limiter = GroqRateLimiter(
        limits=GroqLimits(
            requests_per_minute=1,
            requests_per_day=10,
            tokens_per_minute=1000,
            tokens_per_day=10000,
            max_output_tokens=64,
        )
    )
    limiter.check(100)
    limiter.record(100)
    with pytest.raises(GroqQuotaExceededError):
        limiter.check(100)


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    from api.main import create_app

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_health_endpoint(api_client: TestClient) -> None:
    response = api_client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_schemes_endpoint(api_client: TestClient) -> None:
    response = api_client.get("/api/schemes")
    assert response.status_code == 200
    schemes = response.json()["schemes"]
    assert len(schemes) == 5


def test_chat_empty_message_rejected(api_client: TestClient) -> None:
    response = api_client.post("/api/chat", json={"message": ""})
    assert response.status_code == 422


def test_chat_refusal_without_groq(api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from rag import pipeline as pipeline_module

    mock_pipeline = MagicMock()
    mock_pipeline.handle.return_value = pipeline_module.ChatResponse(
        type="refusal",
        message="No advice.",
    )
    monkeypatch.setattr(pipeline_module, "get_pipeline", lambda: mock_pipeline)

    response = api_client.post(
        "/api/chat",
        json={"message": "Should I invest in HDFC Small Cap?"},
    )
    assert response.status_code == 200
    assert response.json()["type"] == "refusal"
