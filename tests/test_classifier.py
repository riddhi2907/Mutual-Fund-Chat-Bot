"""Unit tests for query intent classification and refusal handling."""

from __future__ import annotations

import pytest

from rag.classifier import (
    Intent,
    build_performance_response,
    build_refusal_response,
    classify,
    detect_pii,
)
from rag.retriever import SchemeResolver
from tests.test_retriever import SCHEMES


@pytest.fixture
def resolver() -> SchemeResolver:
    return SchemeResolver(schemes=SCHEMES)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Should I invest in HDFC Small Cap?", Intent.ADVISORY),
        ("Is HDFC Mid Cap worth buying?", Intent.ADVISORY),
        ("Do you recommend HDFC Large Cap?", Intent.ADVISORY),
    ],
)
def test_classify_advisory(resolver: SchemeResolver, query: str, expected: Intent) -> None:
    assert classify(query, resolver=resolver).intent == expected


@pytest.mark.parametrize(
    "query",
    [
        "Which is better — large cap or mid cap?",
        "Compare HDFC Large Cap and Small Cap returns",
        "HDFC large cap vs mid cap",
    ],
)
def test_classify_comparison(resolver: SchemeResolver, query: str) -> None:
    assert classify(query, resolver=resolver).intent == Intent.COMPARISON


@pytest.mark.parametrize(
    "query",
    [
        "3-year return of HDFC Gold ETF FoF?",
        "What is the CAGR of HDFC Small Cap?",
        "How much would I get if I invest for 5 years?",
    ],
)
def test_classify_performance(resolver: SchemeResolver, query: str) -> None:
    assert classify(query, resolver=resolver).intent == Intent.PERFORMANCE


def test_classify_factual_expense_ratio(resolver: SchemeResolver) -> None:
    result = classify(
        "What is the expense ratio of HDFC Mid Cap Fund Direct Growth?",
        resolver=resolver,
    )
    assert result.intent == Intent.FACTUAL
    assert result.resolved_scheme == "HDFC Mid Cap Fund Direct Growth"


def test_classify_performance_does_not_trigger_on_expense_ratio(
    resolver: SchemeResolver,
) -> None:
    result = classify("Expense ratio of HDFC Mid Cap is 0.75%", resolver=resolver)
    assert result.intent == Intent.FACTUAL


@pytest.mark.parametrize(
    "query",
    [
        "My PAN is ABCDE1234F, check my fund",
        "Aadhaar 1234 5678 9012 linked to SIP",
        "Folio 123456789 — what is my exit load?",
        "OTP sent to my phone",
        "Send answer to john@email.com",
    ],
)
def test_classify_pii(resolver: SchemeResolver, query: str) -> None:
    assert classify(query, resolver=resolver).intent == Intent.PII_DETECTED


def test_detect_pan() -> None:
    assert detect_pii("PAN ABCDE1234F") is True


@pytest.mark.parametrize(
    "query",
    [
        "Expense ratio of SBI Bluechip?",
        "What is the stock price of Reliance?",
        "What is a mutual fund?",
        "What is the ELSS lock-in for HDFC Mid Cap?",
    ],
)
def test_classify_out_of_scope(resolver: SchemeResolver, query: str) -> None:
    assert classify(query, resolver=resolver).intent == Intent.OUT_OF_SCOPE


def test_refusal_templates() -> None:
    refusal = build_refusal_response(Intent.ADVISORY)
    assert refusal["type"] == "refusal"
    assert "investment advice" in refusal["message"].lower()


def test_performance_response_includes_scheme_url(resolver: SchemeResolver) -> None:
    response = build_performance_response(
        "3-year return of HDFC Gold ETF FoF?",
        resolver=resolver,
    )
    assert response["type"] == "scheme_link"
    assert "groww.in" in response["citation_url"]
    assert response["scheme"] == "HDFC Gold ETF Fund of Fund Direct Plan Growth"
