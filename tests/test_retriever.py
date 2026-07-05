"""Unit tests for vector retrieval and scheme alias resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from ingestion.fetcher import SchemeSource
from rag.retriever import (
    FACTUAL_CONTENT_TYPE,
    RetrievedChunk,
    Retriever,
    SchemeResolver,
    assemble_context,
    build_metadata_filter,
    deduplicate_by_section,
    distance_to_score,
    retrieve,
)

SCHEMES = [
    SchemeSource(
        name="HDFC Large Cap Fund Direct Growth",
        category="Equity — Large Cap",
        url="https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        aliases=("large cap", "hdfc large cap"),
    ),
    SchemeSource(
        name="HDFC Mid Cap Fund Direct Growth",
        category="Equity — Mid Cap",
        url="https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
        aliases=("mid cap", "hdfc mid cap"),
    ),
    SchemeSource(
        name="HDFC Small Cap Fund Direct Growth",
        category="Equity — Small Cap",
        url="https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth",
        aliases=("small cap", "hdfc small cap"),
    ),
    SchemeSource(
        name="HDFC Gold ETF Fund of Fund Direct Plan Growth",
        category="Commodities — Gold",
        url="https://groww.in/mutual-funds/hdfc-gold-etf-fund-of-fund-direct-plan-growth",
        aliases=("gold etf", "hdfc gold etf", "gold fund"),
    ),
    SchemeSource(
        name="HDFC Silver ETF FoF Direct Growth",
        category="Commodities — Silver",
        url="https://groww.in/mutual-funds/hdfc-silver-etf-fof-direct-growth",
        aliases=("silver etf", "silver fund", "hdfc silver"),
    ),
]


@pytest.fixture
def resolver() -> SchemeResolver:
    return SchemeResolver(schemes=SCHEMES)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("expense ratio mid cap", "HDFC Mid Cap Fund Direct Growth"),
        ("What is the HDFC Large Cap expense ratio?", "HDFC Large Cap Fund Direct Growth"),
        ("exit load gold etf", "HDFC Gold ETF Fund of Fund Direct Plan Growth"),
        ("benchmark small cap", "HDFC Small Cap Fund Direct Growth"),
        ("silver fund risk", "HDFC Silver ETF FoF Direct Growth"),
        ("minimum SIP large cap", "HDFC Large Cap Fund Direct Growth"),
    ],
)
def test_scheme_resolver_aliases(
    resolver: SchemeResolver,
    query: str,
    expected: str,
) -> None:
    assert resolver.resolve(query) == expected


def test_scheme_resolver_prefers_longer_alias(resolver: SchemeResolver) -> None:
    assert resolver.resolve("gold etf exit load") == (
        "HDFC Gold ETF Fund of Fund Direct Plan Growth"
    )
    assert resolver.resolve("silver etf tax") == "HDFC Silver ETF FoF Direct Growth"


def test_scheme_resolver_no_scheme(resolver: SchemeResolver) -> None:
    assert resolver.resolve("what is an expense ratio") is None


def test_build_metadata_filter_scheme_and_content_type() -> None:
    where = build_metadata_filter(
        scheme_name="HDFC Mid Cap Fund Direct Growth",
        content_type=FACTUAL_CONTENT_TYPE,
    )
    assert where == {
        "$and": [
            {"scheme_name": "HDFC Mid Cap Fund Direct Growth"},
            {"content_type": FACTUAL_CONTENT_TYPE},
        ]
    }


def test_build_metadata_filter_content_type_only() -> None:
    where = build_metadata_filter(scheme_name=None, content_type=FACTUAL_CONTENT_TYPE)
    assert where == {"content_type": FACTUAL_CONTENT_TYPE}


def test_distance_to_score() -> None:
    assert distance_to_score(0.2) == pytest.approx(0.8)


def test_deduplicate_by_section_keeps_highest_score() -> None:
    chunks = [
        RetrievedChunk(
            chunk_id="a-exit_load-001",
            text="section chunk",
            score=0.7,
            scheme_name="Scheme",
            scheme_category="Cat",
            section="exit_load",
            content_type="factual",
            source_url="https://groww.in/a",
            last_fetched_at="2026-07-05T00:00:00Z",
        ),
        RetrievedChunk(
            chunk_id="a-exit_load-002",
            text="label chunk",
            score=0.9,
            scheme_name="Scheme",
            scheme_category="Cat",
            section="exit_load",
            content_type="factual",
            source_url="https://groww.in/a",
            last_fetched_at="2026-07-05T00:00:00Z",
        ),
        RetrievedChunk(
            chunk_id="a-expense_ratio-001",
            text="expense",
            score=0.8,
            scheme_name="Scheme",
            scheme_category="Cat",
            section="expense_ratio",
            content_type="factual",
            source_url="https://groww.in/a",
            last_fetched_at="2026-07-05T00:00:00Z",
        ),
    ]
    deduped = deduplicate_by_section(chunks, top_k=5)
    assert [chunk.chunk_id for chunk in deduped] == [
        "a-exit_load-002",
        "a-expense_ratio-001",
    ]


def test_assemble_context_joins_chunks() -> None:
    chunks = [
        RetrievedChunk(
            chunk_id="a-001",
            text="Fund: A\nExpense ratio: 1%",
            score=0.9,
            scheme_name="A",
            scheme_category="Cat",
            section="expense_ratio",
            content_type="factual",
            source_url="https://groww.in/a",
            last_fetched_at="2026-07-05T00:00:00Z",
        ),
        RetrievedChunk(
            chunk_id="a-002",
            text="Fund: A\nExit load: 1%",
            score=0.8,
            scheme_name="A",
            scheme_category="Cat",
            section="exit_load",
            content_type="factual",
            source_url="https://groww.in/a",
            last_fetched_at="2026-07-05T00:00:00Z",
        ),
    ]
    context = assemble_context(chunks)
    assert "Expense ratio: 1%" in context
    assert "Exit load: 1%" in context
    assert "\n\n" in context


VECTORSTORE = Path("data/vectorstore")
INDEX_READY = (VECTORSTORE / "index_manifest.json").is_file()


@pytest.fixture
def retriever() -> Retriever:
    if not INDEX_READY:
        pytest.skip("Vector index not built")
    return Retriever(vectorstore_dir=VECTORSTORE, score_threshold=0.0)


@pytest.mark.parametrize(
    ("query", "expected_scheme", "expected_section"),
    [
        (
            "expense ratio mid cap",
            "HDFC Mid Cap Fund Direct Growth",
            "expense_ratio",
        ),
        (
            "exit load gold etf",
            "HDFC Gold ETF Fund of Fund Direct Plan Growth",
            "exit_load",
        ),
        (
            "minimum SIP large cap",
            "HDFC Large Cap Fund Direct Growth",
            {"min_sip", "minimum_investments"},
        ),
        (
            "benchmark small cap",
            "HDFC Small Cap Fund Direct Growth",
            "fund_benchmark",
        ),
        (
            "expense ratio HDFC Mid Cap",
            "HDFC Mid Cap Fund Direct Growth",
            "expense_ratio",
        ),
    ],
)
def test_retriever_golden_queries(
    retriever: Retriever,
    query: str,
    expected_scheme: str,
    expected_section: str | set[str],
) -> None:
    result = retriever.retrieve(query)
    assert result.sufficient is True
    assert result.chunks
    top = result.chunks[0]
    assert top.scheme_name == expected_scheme
    if isinstance(expected_section, set):
        assert top.section in expected_section
    else:
        assert top.section == expected_section
    assert top.content_type == FACTUAL_CONTENT_TYPE
    assert top.text in result.context


def test_retriever_silver_fund_risk(resolver: SchemeResolver, retriever: Retriever) -> None:
    result = retriever.retrieve("silver fund risk")
    assert result.resolved_scheme == "HDFC Silver ETF FoF Direct Growth"
    assert result.chunks
    assert result.chunks[0].scheme_name == "HDFC Silver ETF FoF Direct Growth"
    assert all(chunk.content_type == FACTUAL_CONTENT_TYPE for chunk in result.chunks)


def test_retriever_excludes_performance_chunks(retriever: Retriever) -> None:
    result = retriever.retrieve("3 year returns mid cap")
    assert all(chunk.section != "returns_rankings" for chunk in result.chunks)
    assert all(chunk.content_type != "performance" for chunk in result.chunks)


def test_retriever_large_cap_alias(retriever: Retriever) -> None:
    result = retriever.retrieve("large cap expense ratio")
    assert result.resolved_scheme == "HDFC Large Cap Fund Direct Growth"
    assert result.chunks[0].scheme_name == "HDFC Large Cap Fund Direct Growth"


def test_retrieve_module_helper(retriever: Retriever, monkeypatch: pytest.MonkeyPatch) -> None:
    import rag.retriever as retriever_module

    monkeypatch.setattr(retriever_module, "_default_retriever", retriever)
    result = retrieve("expense ratio mid cap")
    assert result.chunks[0].section == "expense_ratio"
