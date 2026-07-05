"""Unit tests for response validation rules."""

from __future__ import annotations

import pytest

from rag.retriever import RetrievedChunk
from rag.validator import (
    FOOTER_PREFIX,
    count_answer_sentences,
    validate_and_fix,
)

SAMPLE_CHUNK = RetrievedChunk(
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

ALLOWLIST = {"https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"}


def test_validate_compliant_answer() -> None:
    message = (
        "The expense ratio of HDFC Mid Cap Fund Direct Growth is 0.75%.\n\n"
        "Source: https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth\n\n"
        "Last updated from sources: 2026-07-05"
    )
    result = validate_and_fix(message, (SAMPLE_CHUNK,), allowlist=ALLOWLIST)
    assert result.valid is True
    assert result.citation_url.endswith("hdfc-mid-cap-fund-direct-growth")
    assert result.scheme == "HDFC Mid Cap Fund Direct Growth"
    assert result.last_updated == "2026-07-05"


def test_validate_truncates_long_answers() -> None:
    message = (
        "Sentence one. Sentence two. Sentence three. Sentence four.\n\n"
        "Source: https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth\n\n"
        "Last updated from sources: 2026-07-05"
    )
    result = validate_and_fix(message, (SAMPLE_CHUNK,), allowlist=ALLOWLIST)
    assert count_answer_sentences(result.message) <= 3
    assert "truncated_sentences" in result.fixes_applied


def test_validate_injects_correct_groww_url() -> None:
    message = (
        "The expense ratio is 0.75%.\n\n"
        "Source: https://groww.in/blog/some-post\n\n"
        "Last updated from sources: 2026-07-05"
    )
    result = validate_and_fix(message, (SAMPLE_CHUNK,), allowlist=ALLOWLIST)
    assert "fixed_source_url" in result.fixes_applied
    assert result.citation_url == "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"


def test_validate_appends_footer_when_missing() -> None:
    message = (
        "The expense ratio is 0.75%.\n\n"
        "Source: https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"
    )
    result = validate_and_fix(message, (SAMPLE_CHUNK,), allowlist=ALLOWLIST)
    assert FOOTER_PREFIX in result.message
    assert "appended_footer" in result.fixes_applied


def test_validate_rejects_advisory_language() -> None:
    message = (
        "You should invest in this fund because it is good.\n\n"
        "Source: https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth\n\n"
        "Last updated from sources: 2026-07-05"
    )
    result = validate_and_fix(message, (SAMPLE_CHUNK,), allowlist=ALLOWLIST)
    assert result.valid is False
    assert "advisory_language_detected" in result.fixes_applied


def test_validate_rejects_performance_figures() -> None:
    message = (
        "The fund returned 20% last year.\n\n"
        "Source: https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth\n\n"
        "Last updated from sources: 2026-07-05"
    )
    result = validate_and_fix(message, (SAMPLE_CHUNK,), allowlist=ALLOWLIST)
    assert result.valid is False
    assert "performance_figures_detected" in result.fixes_applied


def test_expense_ratio_percent_is_allowed() -> None:
    message = (
        "The expense ratio is 0.75%.\n\n"
        "Source: https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth\n\n"
        "Last updated from sources: 2026-07-05"
    )
    result = validate_and_fix(message, (SAMPLE_CHUNK,), allowlist=ALLOWLIST)
    assert result.valid is True
