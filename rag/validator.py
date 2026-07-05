"""Response validator for sentence count, citations, and compliance rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from urllib.parse import urlparse

from ingestion.fetcher import load_sources
from rag.retriever import RetrievedChunk

FOOTER_PREFIX = "Last updated from sources:"
GROWW_DOMAIN = "groww.in"

ADVISORY_PATTERNS = (
    "i recommend",
    "you should",
    "you must",
    "better fund",
    "should invest",
    "worth buying",
)

PERFORMANCE_RETURN_PATTERN = re.compile(
    r"\b\d+(\.\d+)?\s*%.*\b(return|returns|cagr|annualised|annualized|year)\b",
    re.IGNORECASE,
)

URL_PATTERN = re.compile(r"https?://[^\s)>\"]+", re.IGNORECASE)
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class ValidationResult:
    message: str
    citation_url: str
    scheme: str
    last_updated: str
    valid: bool
    fixes_applied: tuple[str, ...] = ()


def _normalize_url(url: str) -> str:
    return url.rstrip(".,);]")


def extract_urls(text: str) -> list[str]:
    return [_normalize_url(match.group(0)) for match in URL_PATTERN.finditer(text)]


def is_groww_scheme_url(url: str, allowlist: set[str]) -> bool:
    parsed = urlparse(url)
    if GROWW_DOMAIN not in parsed.netloc:
        return False
    normalized = url.rstrip("/")
    return normalized in allowlist or f"{normalized}/" in allowlist


def count_answer_sentences(message: str) -> int:
    """Count sentences in the answer body (before Source/footer)."""
    body = message.split("Source:")[0].split(FOOTER_PREFIX)[0].strip()
    if not body:
        return 0
    sentences = [part.strip() for part in SENTENCE_SPLIT_PATTERN.split(body) if part.strip()]
    return len(sentences)


def truncate_to_three_sentences(message: str) -> str:
    body = message.split("Source:")[0].split(FOOTER_PREFIX)[0].strip()
    tail = ""
    if "Source:" in message:
        tail = message[message.index("Source:") :]
    elif FOOTER_PREFIX in message:
        tail = message[message.index(FOOTER_PREFIX) :]

    sentences = [part.strip() for part in SENTENCE_SPLIT_PATTERN.split(body) if part.strip()]
    truncated_body = " ".join(sentences[:3])
    if tail:
        return f"{truncated_body}\n\n{tail.strip()}"
    return truncated_body


def contains_advisory_language(text: str) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in ADVISORY_PATTERNS)


def contains_performance_figures(text: str) -> bool:
    return bool(PERFORMANCE_RETURN_PATTERN.search(text))


def _newest_fetch_date(chunks: Iterable[RetrievedChunk]) -> str:
    dates = [chunk.last_fetched_at for chunk in chunks if chunk.last_fetched_at]
    if not dates:
        return datetime.utcnow().strftime("%Y-%m-%d")
    newest = max(dates)
    return newest[:10]


def _primary_chunk(chunks: tuple[RetrievedChunk, ...]) -> RetrievedChunk:
    return chunks[0]


def _build_allowlist() -> set[str]:
    urls: set[str] = set()
    for scheme in load_sources():
        urls.add(scheme.url.rstrip("/"))
    return urls


def ensure_footer(message: str, last_updated: str) -> str:
    footer = f"{FOOTER_PREFIX} {last_updated}"
    if FOOTER_PREFIX in message:
        return re.sub(
            rf"{re.escape(FOOTER_PREFIX)}\s*[\d-]+",
            footer,
            message,
            count=1,
        )
    return f"{message.rstrip()}\n\n{footer}"


def ensure_source_line(message: str, citation_url: str) -> str:
    source_line = f"Source: {citation_url}"
    urls = extract_urls(message)
    if "Source:" in message:
        return re.sub(r"Source:\s*https?://\S+", source_line, message, count=1)
    if urls:
        return message.replace(urls[0], citation_url, 1)
    return f"{message.rstrip()}\n\n{source_line}"


def validate_and_fix(
    message: str,
    chunks: tuple[RetrievedChunk, ...],
    *,
    allowlist: set[str] | None = None,
) -> ValidationResult:
    """Validate a Groq draft and apply deterministic fixes without extra API calls."""
    if not chunks:
        raise ValueError("At least one retrieved chunk is required for validation")

    allow = allowlist or _build_allowlist()
    primary = _primary_chunk(chunks)
    citation_url = primary.source_url.rstrip("/")
    scheme = primary.scheme_name
    last_updated = _newest_fetch_date(chunks)
    fixes: list[str] = []

    fixed = message.strip()
    if count_answer_sentences(fixed) > 3:
        fixed = truncate_to_three_sentences(fixed)
        fixes.append("truncated_sentences")

    urls = extract_urls(fixed)
    valid_urls = [url for url in urls if is_groww_scheme_url(url, allow)]
    if len(valid_urls) != 1 or urls != valid_urls:
        fixed = ensure_source_line(fixed, citation_url)
        fixes.append("fixed_source_url")

    if FOOTER_PREFIX not in fixed:
        fixed = ensure_footer(fixed, last_updated)
        fixes.append("appended_footer")

    if contains_advisory_language(fixed):
        fixes.append("advisory_language_detected")

    if contains_performance_figures(fixed):
        fixes.append("performance_figures_detected")

    valid = (
        count_answer_sentences(fixed) <= 3
        and len(extract_urls(fixed)) == 1
        and is_groww_scheme_url(extract_urls(fixed)[0], allow)
        and FOOTER_PREFIX in fixed
        and "advisory_language_detected" not in fixes
        and "performance_figures_detected" not in fixes
    )

    return ValidationResult(
        message=fixed,
        citation_url=citation_url,
        scheme=scheme,
        last_updated=last_updated,
        valid=valid,
        fixes_applied=tuple(fixes),
    )
