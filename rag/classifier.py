"""Query intent classifier and refusal handler for non-factual queries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from ingestion.fetcher import SchemeSource, load_sources
from rag.retriever import SchemeResolver

REFUSAL_MESSAGE = (
    "I can only answer factual questions about the five supported HDFC Mutual Fund schemes "
    "using information from their Groww fund pages. I cannot provide investment advice or "
    "fund recommendations."
)

OUT_OF_SCOPE_MESSAGE = (
    "I can only answer factual questions about the five supported HDFC Mutual Fund schemes "
    "listed on Groww (Large Cap, Mid Cap, Small Cap, Gold ETF FoF, and Silver ETF FoF). "
    "I cannot help with funds or topics outside this scope."
)

PII_MESSAGE = (
    "For your privacy, please do not share personal information such as PAN, Aadhaar, "
    "account numbers, or OTPs. Ask a factual question about one of the five supported "
    "HDFC schemes instead."
)

PERFORMANCE_MESSAGE = (
    "For performance details, please refer to the fund page."
)


class Intent(str, Enum):
    FACTUAL = "FACTUAL"
    ADVISORY = "ADVISORY"
    COMPARISON = "COMPARISON"
    PERFORMANCE = "PERFORMANCE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    PII_DETECTED = "PII_DETECTED"


@dataclass(frozen=True)
class ClassificationResult:
    intent: Intent
    resolved_scheme: str | None = None


PAN_PATTERN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.IGNORECASE)
AADHAAR_PATTERN = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)

PII_KEYWORDS = (
    "account number",
    "folio",
    "otp",
    "one time password",
    "aadhaar",
    "aadhar",
)

ADVISORY_PATTERNS = (
    "should i invest",
    "should i buy",
    "is it good",
    "is this good",
    "recommend",
    "worth buying",
    "worth investing",
    "good investment",
    "better to invest",
)

COMPARISON_PATTERNS = (
    "which is better",
    "which fund is better",
    "compare",
    " vs ",
    " versus ",
)

PERFORMANCE_PATTERNS = (
    "return",
    "returns",
    "performance",
    "cagr",
    "annualised",
    "annualized",
    "how much would",
    "how much will",
    "3-year",
    "3 year",
    "5-year",
    "5 year",
    "1-year",
    "1 year",
)

OUT_OF_SCOPE_PATTERNS = (
    "sbi ",
    "sbi bluechip",
    "icici",
    "axis mutual",
    "nippon",
    "reliance stock",
    "stock price",
    "what is a mutual fund",
    "what is mutual fund",
    "hdfc flexi cap",
    "elss lock",
    "elss lock-in",
)

OTHER_AMC_PATTERN = re.compile(
    r"\b(sbi|icici|axis|nippon|uti|kotak|dsp|franklin|parag parikh)\b",
    re.IGNORECASE,
)

PERFORMANCE_PERCENT_PATTERN = re.compile(
    r"\b\d+(\.\d+)?\s*%\b.*\b(return|year|cagr|annualised|annualized)\b",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def count_resolved_schemes(text: str, resolver: SchemeResolver) -> int:
    """Count distinct supported schemes mentioned in the query."""
    normalized = _normalize(text)
    found: set[str] = set()
    for pattern, scheme_name in resolver._patterns:
        if pattern in normalized:
            found.add(scheme_name)
    return len(found)


def detect_pii(text: str) -> bool:
    if PAN_PATTERN.search(text):
        return True
    if AADHAAR_PATTERN.search(text):
        return True
    if EMAIL_PATTERN.search(text):
        return True
    normalized = _normalize(text)
    return _contains_any(normalized, PII_KEYWORDS)


def detect_advisory(text: str) -> bool:
    return _contains_any(_normalize(text), ADVISORY_PATTERNS)


def detect_comparison(text: str, resolver: SchemeResolver) -> bool:
    normalized = _normalize(text)
    if _contains_any(normalized, COMPARISON_PATTERNS):
        return True
    if " or " in normalized and count_resolved_schemes(normalized, resolver) >= 2:
        return True
    return False


def detect_performance(text: str) -> bool:
    normalized = _normalize(text)
    if _contains_any(normalized, PERFORMANCE_PATTERNS):
        return True
    return bool(PERFORMANCE_PERCENT_PATTERN.search(normalized))


def detect_out_of_scope(text: str, resolver: SchemeResolver) -> bool:
    normalized = _normalize(text)
    if OTHER_AMC_PATTERN.search(normalized):
        return True
    if _contains_any(normalized, OUT_OF_SCOPE_PATTERNS):
        return True
    if "elss" in normalized and resolver.resolve(text) is None:
        return True
    if _contains_any(
        normalized,
        ("what is a mutual fund", "what is mutual fund"),
    ) and resolver.resolve(text) is None:
        return True
    return False


def classify(
    query: str,
    *,
    resolver: SchemeResolver | None = None,
) -> ClassificationResult:
    """Classify a user query into an intent (rule-based; no Groq call)."""
    scheme_resolver = resolver or SchemeResolver()
    resolved_scheme = scheme_resolver.resolve(query)

    if detect_pii(query):
        return ClassificationResult(Intent.PII_DETECTED, resolved_scheme)
    if detect_advisory(query):
        return ClassificationResult(Intent.ADVISORY, resolved_scheme)
    if detect_comparison(query, scheme_resolver):
        return ClassificationResult(Intent.COMPARISON, resolved_scheme)
    if detect_performance(query):
        return ClassificationResult(Intent.PERFORMANCE, resolved_scheme)
    if detect_out_of_scope(query, scheme_resolver):
        return ClassificationResult(Intent.OUT_OF_SCOPE, resolved_scheme)

    return ClassificationResult(Intent.FACTUAL, resolved_scheme)


def refusal_message(intent: Intent) -> str:
    if intent == Intent.PII_DETECTED:
        return PII_MESSAGE
    if intent == Intent.OUT_OF_SCOPE:
        return OUT_OF_SCOPE_MESSAGE
    return REFUSAL_MESSAGE


def build_refusal_response(intent: Intent) -> dict[str, str]:
    return {"type": "refusal", "message": refusal_message(intent)}


def get_scheme_url(scheme_name: str, schemes: list[SchemeSource] | None = None) -> str | None:
    for scheme in schemes or load_sources():
        if scheme.name == scheme_name:
            return scheme.url
    return None


def build_performance_response(
    query: str,
    *,
    resolver: SchemeResolver | None = None,
    schemes: list[SchemeSource] | None = None,
) -> dict[str, str]:
    scheme_resolver = resolver or SchemeResolver()
    scheme_name = scheme_resolver.resolve(query)
    citation_url = get_scheme_url(scheme_name, schemes) if scheme_name else None
    response: dict[str, str] = {
        "type": "scheme_link",
        "message": PERFORMANCE_MESSAGE,
    }
    if citation_url:
        response["citation_url"] = citation_url
    if scheme_name:
        response["scheme"] = scheme_name
    return response
