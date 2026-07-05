"""Unit tests for section-aware chunker (Phase 1.4 / 1.5)."""

import json
from pathlib import Path

import pytest

from ingestion.chunker import (
    chunk_all_processed,
    chunk_processed_scheme,
    write_chunks_jsonl,
)

FIXTURE_SCHEME = {
    "slug": "hdfc-mid-cap-fund-direct-growth",
    "source_url": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
    "fund_name": "HDFC Mid Cap Fund Direct Growth",
    "category": "Equity — Mid Cap",
    "label_values": {
        "Estimate returns on a SIP": "SIP calculator",
        "NAV: 03 Jul '26": "₹229.59",
        "Min. for SIP": "₹100",
        "Fund size (AUM)": "₹97,350.48 Cr",
        "Expense ratio": "0.75%",
        "Rating": "5",
        "Fund benchmark": "NIFTY Midcap 150 Total Return Index",
        "Total AUM": "₹9,34,237.77 Cr",
        "Phone": "022 – 66316333",
    },
    "sections": {
        "Minimum investments": "Min. for 1st investment ₹100 Min. for 2nd investment ₹100 Min. for SIP ₹100",
        "Exit load": "Exit load of 1% if redeemed within 1 year.",
        "Stamp duty on investment:0.005% (from July 1st, 2020)": "from July 1st 2020",
        "Tax implication": "If you redeem within one year, returns are taxed at 20%.",
        "Investment Objective": "The scheme seeks to provide long-term capital appreciation.",
    },
    "tables": [
        {
            "title": "Returns and rankings",
            "text": "Returns and rankings\nName | 3Y | 5Y\nFund returns | +21.0% | +20.7%",
        }
    ],
    "text": "duplicate page content that must not be chunked",
    "parsed_at": "2026-07-05T17:10:32.367587+00:00",
}


def test_chunk_processed_scheme_produces_twelve_chunks() -> None:
    chunks = chunk_processed_scheme(FIXTURE_SCHEME)
    assert len(chunks) == 12


def test_chunk_metadata_fields() -> None:
    chunks = chunk_processed_scheme(FIXTURE_SCHEME)
    expense = next(c for c in chunks if c.section == "expense_ratio")

    assert expense.chunk_id == "hdfc-mid-cap-fund-direct-growth-expense_ratio-001"
    assert expense.scheme_name == "HDFC Mid Cap Fund Direct Growth"
    assert expense.scheme_category == "Equity — Mid Cap"
    assert expense.source_url == FIXTURE_SCHEME["source_url"]
    assert expense.source_domain == "groww.in"
    assert expense.content_type == "factual"
    assert expense.last_fetched_at == "2026-07-05T17:10:32.367587Z"
    assert expense.token_count > 0


def test_chunk_text_template() -> None:
    chunks = chunk_processed_scheme(FIXTURE_SCHEME)
    expense = next(c for c in chunks if c.section == "expense_ratio")

    assert expense.text == (
        "Fund: HDFC Mid Cap Fund Direct Growth\n"
        "Category: Equity — Mid Cap\n"
        "Expense ratio: 0.75%"
    )


def test_excluded_labels_and_text_field_not_chunked() -> None:
    chunks = chunk_processed_scheme(FIXTURE_SCHEME)
    all_text = "\n".join(c.text for c in chunks)

    assert "SIP calculator" not in all_text
    assert "022 – 66316333" not in all_text
    assert "duplicate page content" not in all_text
    assert "₹9,34,237.77 Cr" not in all_text


def test_performance_table_chunk() -> None:
    chunks = chunk_processed_scheme(FIXTURE_SCHEME)
    returns = next(c for c in chunks if c.section == "returns_rankings")

    assert returns.content_type == "performance"
    assert "Returns and rankings:" in returns.text
    assert "Fund returns | +21.0%" in returns.text


def test_stamp_duty_heading_normalized() -> None:
    chunks = chunk_processed_scheme(FIXTURE_SCHEME)
    stamp = next(c for c in chunks if c.section == "stamp_duty")

    assert "Stamp duty on investment: 0.005%" in stamp.text


def test_key_factual_sections_present() -> None:
    chunks = chunk_processed_scheme(FIXTURE_SCHEME)
    sections = {c.section for c in chunks}

    assert sections >= {
        "expense_ratio",
        "min_sip",
        "fund_benchmark",
        "minimum_investments",
        "exit_load",
        "tax_implication",
        "returns_rankings",
    }


def test_chunk_all_processed_from_fixture_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    (processed_dir / "scheme-a.json").write_text(
        json.dumps({**FIXTURE_SCHEME, "slug": "scheme-a"}),
        encoding="utf-8",
    )

    chunks = chunk_all_processed(processed_dir=processed_dir)
    assert len(chunks) == 12


def test_write_chunks_jsonl(tmp_path: Path) -> None:
    chunks = chunk_processed_scheme(FIXTURE_SCHEME)
    output_path = tmp_path / "chunks.jsonl"
    write_chunks_jsonl(chunks, output_path=output_path)

    lines = output_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 12

    first = json.loads(lines[0])
    required = {
        "chunk_id",
        "scheme_name",
        "scheme_category",
        "source_url",
        "source_domain",
        "section",
        "content_type",
        "text",
        "last_fetched_at",
        "token_count",
    }
    assert required.issubset(first.keys())


@pytest.mark.parametrize(
    "json_path",
    [
        Path("data/processed/hdfc-large-cap-fund-direct-growth.json"),
        Path("data/processed/hdfc-mid-cap-fund-direct-growth.json"),
        Path("data/processed/hdfc-small-cap-fund-direct-growth.json"),
        Path("data/processed/hdfc-gold-etf-fund-of-fund-direct-plan-growth.json"),
        Path("data/processed/hdfc-silver-etf-fof-direct-growth.json"),
    ],
)
def test_real_processed_files_produce_twelve_chunks_each(json_path: Path) -> None:
    if not json_path.is_file():
        pytest.skip(f"Processed file not present: {json_path}")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    chunks = chunk_processed_scheme(data)
    assert len(chunks) == 12

    sections = [c.section for c in chunks]
    assert sections.count("expense_ratio") == 1
    assert sections.count("exit_load") == 1
    assert sections.count("returns_rankings") == 1


def test_gold_etf_exit_load_wording() -> None:
    json_path = Path("data/processed/hdfc-gold-etf-fund-of-fund-direct-plan-growth.json")
    if not json_path.is_file():
        pytest.skip("Gold ETF processed file not present")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    exit_load = next(c for c in chunk_processed_scheme(data) if c.section == "exit_load")
    assert "15 days" in exit_load.text
