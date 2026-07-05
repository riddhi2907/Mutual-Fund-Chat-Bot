"""Section-aware chunker with metadata enrichment for RAG indexing."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DEFAULT_CHUNKS_DIR = PROJECT_ROOT / "data" / "chunks"
DEFAULT_CHUNKS_PATH = DEFAULT_CHUNKS_DIR / "chunks.jsonl"

FAQ_LABELS: frozenset[str] = frozenset(
    {
        "Expense ratio",
        "Min. for SIP",
        "Fund benchmark",
        "Fund size (AUM)",
        "Rating",
    }
)

EXCLUDED_LABELS: frozenset[str] = frozenset(
    {
        "Estimate returns on a SIP",
        "Total AUM",
        "Phone",
        "Website",
        "Address",
        "Email",
        "Custodian",
        "Registrar & Transfer Agent",
        "Date of Incorporation",
        "Launch Date",
    }
)

LABEL_SECTION_SLUGS: dict[str, str] = {
    "Expense ratio": "expense_ratio",
    "Min. for SIP": "min_sip",
    "Fund benchmark": "fund_benchmark",
    "Fund size (AUM)": "fund_aum",
    "Rating": "rating",
}

SECTION_HEADING_SLUGS: dict[str, tuple[str, str]] = {
    "Exit load": ("exit_load", "Exit load"),
    "Minimum investments": ("minimum_investments", "Minimum investments"),
    "Tax implication": ("tax_implication", "Tax implication"),
    "Investment Objective": ("investment_objective", "Investment Objective"),
}

ContentType = str  # "factual" | "performance" | "admin"


@dataclass(frozen=True)
class Chunk:
    """One retrieval unit with enriched metadata for ``chunks.jsonl``."""

    chunk_id: str
    scheme_name: str
    scheme_category: str
    source_url: str
    source_domain: str
    section: str
    content_type: ContentType
    text: str
    last_fetched_at: str
    token_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "unknown"


def _count_tokens(text: str) -> int:
    """Approximate token count via whitespace split (no tiktoken dependency)."""
    return len(text.split())


def _format_timestamp(parsed_at: str | None) -> str:
    if not parsed_at:
        return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    normalized = parsed_at.replace("+00:00", "Z")
    if not normalized.endswith("Z") and "+" not in normalized:
        normalized += "Z"
    return normalized


def _source_domain(source_url: str) -> str:
    hostname = urlparse(source_url).hostname or ""
    if hostname.startswith("www."):
        return hostname[4:]
    return hostname


def _build_chunk_text(
    fund_name: str,
    category: str | None,
    label: str,
    value: str,
) -> str:
    lines = [f"Fund: {fund_name}"]
    if category:
        lines.append(f"Category: {category}")
    lines.append(f"{label}: {value}")
    return "\n".join(lines)


def _label_section_slug(label: str) -> str | None:
    if label in LABEL_SECTION_SLUGS:
        return LABEL_SECTION_SLUGS[label]
    if label.startswith("NAV:"):
        return "nav"
    return None


def _should_chunk_label(label: str) -> bool:
    if label in EXCLUDED_LABELS:
        return False
    if label in FAQ_LABELS:
        return True
    return label.startswith("NAV:")


def _normalize_stamp_duty_text(heading: str, body: str) -> str:
    normalized_heading = re.sub(r":(\S)", r": \1", heading, count=1)
    body = body.strip()
    if body and body.lower() not in normalized_heading.lower():
        return f"{normalized_heading}. {body}"
    return normalized_heading


def _resolve_section_heading(heading: str) -> tuple[str, str] | None:
    if heading in SECTION_HEADING_SLUGS:
        return SECTION_HEADING_SLUGS[heading]
    if heading.lower().startswith("stamp duty"):
        return ("stamp_duty", "Stamp duty on investment")
    return None


def _table_section_slug(title: str | None) -> str:
    if title and "return" in title.lower():
        return "returns_rankings"
    return _slugify(title or "table")


def _make_chunk_id(slug: str, section: str, sequence: int) -> str:
    return f"{slug}-{section}-{sequence:03d}"


def chunk_processed_scheme(data: dict[str, Any]) -> list[Chunk]:
    """
    Build section-aware chunks from one ``data/processed/{slug}.json`` file.

    Skips the duplicate ``text`` field per ImplementationPlan Phase 1.4.
    """
    slug = data.get("slug")
    if not slug:
        raise ValueError("Processed JSON missing required field: slug")

    fund_name = data.get("fund_name") or ""
    category = data.get("category")
    source_url = data.get("source_url") or ""
    if not source_url:
        raise ValueError(f"Processed JSON missing source_url for slug={slug}")

    last_fetched_at = _format_timestamp(data.get("parsed_at"))
    source_domain = _source_domain(source_url)

    chunks: list[Chunk] = []
    section_counts: dict[str, int] = {}

    def append_chunk(
        *,
        section: str,
        content_type: ContentType,
        label: str,
        value: str,
    ) -> None:
        if not value.strip():
            return
        section_counts[section] = section_counts.get(section, 0) + 1
        sequence = section_counts[section]
        text = _build_chunk_text(fund_name, category, label, value)
        chunks.append(
            Chunk(
                chunk_id=_make_chunk_id(slug, section, sequence),
                scheme_name=fund_name,
                scheme_category=category or "",
                source_url=source_url,
                source_domain=source_domain,
                section=section,
                content_type=content_type,
                text=text,
                last_fetched_at=last_fetched_at,
                token_count=_count_tokens(text),
            )
        )

    for label, value in data.get("label_values", {}).items():
        if not _should_chunk_label(label):
            continue
        section = _label_section_slug(label)
        if section is None:
            continue
        append_chunk(
            section=section,
            content_type="factual",
            label=label,
            value=str(value),
        )

    for heading, body in data.get("sections", {}).items():
        resolved = _resolve_section_heading(heading)
        if resolved is None:
            logger.warning("Unknown section heading %r in %s — skipping", heading, slug)
            continue
        section, display_label = resolved
        if section == "stamp_duty":
            value = _normalize_stamp_duty_text(heading, str(body))
        else:
            value = str(body).strip()
        append_chunk(
            section=section,
            content_type="factual",
            label=display_label,
            value=value,
        )

    for table in data.get("tables", []):
        table_text = table.get("text") or ""
        if not table_text.strip():
            continue
        title = table.get("title")
        section = _table_section_slug(title)
        label = title or "Returns and rankings"
        append_chunk(
            section=section,
            content_type="performance",
            label=f"{label}:",
            value=table_text,
        )

    return chunks


def load_processed_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def chunk_all_processed(
    processed_dir: Path | None = None,
) -> list[Chunk]:
    """Chunk every ``*.json`` scheme file in ``data/processed/`` (excludes index.json)."""
    processed_dir = processed_dir or DEFAULT_PROCESSED_DIR
    chunks: list[Chunk] = []

    json_paths = sorted(
        path
        for path in processed_dir.glob("*.json")
        if path.name != "index.json"
    )
    if not json_paths:
        raise FileNotFoundError(f"No processed scheme JSON files found in {processed_dir}")

    for json_path in json_paths:
        data = load_processed_json(json_path)
        scheme_chunks = chunk_processed_scheme(data)
        logger.info("Chunked %s → %d chunks", json_path.name, len(scheme_chunks))
        chunks.extend(scheme_chunks)

    return chunks


def write_chunks_jsonl(
    chunks: list[Chunk],
    output_path: Path | None = None,
) -> Path:
    """Write chunks to ``data/chunks/chunks.jsonl``."""
    output_path = output_path or DEFAULT_CHUNKS_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")

    logger.info("Wrote %d chunks to %s", len(chunks), output_path)
    return output_path


def build_chunks(
    processed_dir: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    """Chunk all processed JSON files and write ``chunks.jsonl``."""
    chunks = chunk_all_processed(processed_dir=processed_dir)
    return write_chunks_jsonl(chunks, output_path=output_path)
