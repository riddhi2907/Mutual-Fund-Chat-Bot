"""HTML parser and normalizer for Groww scheme page content."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup, Tag
from readability import Document

from ingestion.fetcher import SchemeSource, load_sources, url_to_slug

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

REMOVE_TAGS = {"script", "style", "noscript", "svg", "iframe"}
REMOVE_STRUCTURE_TAGS = {"nav", "footer"}
REMOVE_CLASS_FRAGMENTS = (
    "compareSimilarFunds",
    "footer",
    "Footer",
    "returnCalculator",
    "freshchat",
    "cookie",
    "navbar",
    "siteMap",
    "globalFooter",
)
SKIP_SECTION_HEADINGS = {
    "compare similar funds",
    "return calculator",
    "understand terms",
    "fund management",
}
SKIP_TABLE_MARKERS = (
    "would've become",
    "historic returns",
    "sector",
    "instruments",
    "compare",
    "fund size(cr)",
)
CATEGORY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"equity[\s\S]{0,40}large\s*cap", "Equity — Large Cap"),
    (r"equity[\s\S]{0,40}mid\s*cap", "Equity — Mid Cap"),
    (r"equity[\s\S]{0,40}small\s*cap", "Equity — Small Cap"),
    (r"commodit(?:y|ies)[\s\S]{0,40}gold", "Commodities — Gold"),
    (r"commodit(?:y|ies)[\s\S]{0,40}silver", "Commodities — Silver"),
    (r"gold[\s\S]{0,40}etf", "Commodities — Gold"),
    (r"silver[\s\S]{0,40}etf", "Commodities — Silver"),
)


@dataclass(frozen=True)
class ParsedTable:
    """A table extracted from a Groww scheme page."""

    title: str | None
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def to_text(self) -> str:
        lines: list[str] = []
        if self.title:
            lines.append(self.title)
        if self.headers:
            lines.append(" | ".join(self.headers))
        for row in self.rows:
            lines.append(" | ".join(row))
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "headers": list(self.headers),
            "rows": [list(row) for row in self.rows],
            "text": self.to_text(),
        }


@dataclass
class ParsedSchemePage:
    """Structured parse result for one Groww scheme page."""

    fund_name: str
    category: str | None
    sections: dict[str, str] = field(default_factory=dict)
    tables: list[ParsedTable] = field(default_factory=list)
    label_values: dict[str, str] = field(default_factory=dict)
    text: str = ""

    def to_processed_text(self) -> str:
        """Render parsed content as plain text for ``data/processed/``."""
        blocks: list[str] = [f"Fund: {self.fund_name}"]
        if self.category:
            blocks.append(f"Category: {self.category}")

        if self.label_values:
            blocks.append("\n## Fund Overview")
            for label, value in self.label_values.items():
                blocks.append(f"{label}: {value}")

        for heading, content in self.sections.items():
            blocks.append(f"\n## {heading}")
            blocks.append(content)

        if self.tables:
            blocks.append("\n## Tables")
            for index, table in enumerate(self.tables, start=1):
                title = table.title or f"Table {index}"
                blocks.append(f"\n### {title}")
                blocks.append(table.to_text())

        if self.text:
            blocks.append("\n## Page Content")
            blocks.append(self.text)

        return "\n".join(blocks).strip() + "\n"

    def to_review_dict(
        self,
        *,
        slug: str | None = None,
        source_url: str | None = None,
    ) -> dict[str, object]:
        """Structured dict for JSON review files in ``data/processed/``."""
        return {
            "slug": slug,
            "source_url": source_url,
            "fund_name": self.fund_name,
            "category": self.category,
            "label_values": self.label_values,
            "sections": self.sections,
            "tables": [table.to_dict() for table in self.tables],
            "text": self.text,
            "parsed_at": datetime.now(timezone.utc).isoformat(),
        }


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_heading(text: str) -> str:
    text = re.sub(r"^About(?=[A-Z])", "About ", text)
    return _normalize_whitespace(text)


def _remove_section(heading: Tag) -> None:
    """Remove a heading and sibling content until the next heading."""
    nodes_to_remove: list[Tag] = [heading]
    for sibling in heading.find_next_siblings():
        if isinstance(sibling, Tag) and sibling.name in {"h2", "h3", "h4"}:
            break
        if isinstance(sibling, Tag):
            nodes_to_remove.append(sibling)
    for node in nodes_to_remove:
        node.decompose()


def _should_skip_section(heading: str) -> bool:
    lowered = heading.lower()
    if lowered in SKIP_SECTION_HEADINGS:
        return True
    if lowered.startswith("holdings"):
        return True
    return False


def _class_contains(fragment: str, class_value: object) -> bool:
    if not class_value:
        return False
    if isinstance(class_value, str):
        return fragment in class_value
    return any(fragment in value for value in class_value)


def _remove_boilerplate(soup: BeautifulSoup) -> None:
    for tag_name in REMOVE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for tag_name in REMOVE_STRUCTURE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for tag in list(soup.find_all(True)):
        if not isinstance(tag, Tag) or tag.attrs is None:
            continue
        class_value = tag.get("class")
        if any(_class_contains(fragment, class_value) for fragment in REMOVE_CLASS_FRAGMENTS):
            tag.decompose()
            continue
        tag_id = tag.get("id") or ""
        if any(fragment.lower() in tag_id.lower() for fragment in REMOVE_CLASS_FRAGMENTS):
            tag.decompose()

    for text_node in soup.find_all(string=re.compile(r"All rights reserved", re.I)):
        parent = text_node.parent
        for _ in range(8):
            if parent is None or parent.name == "body":
                break
            if parent.name in {"footer", "section", "div"}:
                parent.decompose()
                break
            parent = parent.parent

    for heading in list(soup.find_all(["h2", "h3", "h4"])):
        title = heading.get_text(strip=True)
        if _should_skip_section(title):
            _remove_section(heading)


def _extract_fund_name(soup: BeautifulSoup, fallback: str | None) -> str:
    h1 = soup.find("h1")
    if h1:
        name = _normalize_whitespace(h1.get_text(" ", strip=True))
        if name:
            return name

    if soup.title and soup.title.string:
        title = soup.title.string.split(" - ")[0].strip()
        if title:
            return title

    if fallback:
        return fallback

    raise ValueError("Could not extract fund name from HTML")


def _extract_category(
    soup: BeautifulSoup,
    fund_name: str,
    fallback: str | None,
) -> str | None:
    h1 = soup.find("h1")
    if h1 and h1.parent:
        nearby = _normalize_whitespace(h1.parent.get_text(" ", strip=True))
        lowered = nearby.lower()
        for pattern, category in CATEGORY_PATTERNS:
            if re.search(pattern, lowered, re.I):
                return category

    if fallback:
        return fallback

    meta = soup.find("meta", attrs={"property": "og:description"})
    if meta and meta.get("content"):
        lowered = meta["content"].lower()
        for pattern, category in CATEGORY_PATTERNS:
            if re.search(pattern, lowered, re.I):
                return category

    return None


LABEL_CLASS_MARKERS = ("contentSecondary", "contentTertiary", "bodyBase")
VALUE_CLASS_MARKERS = ("bodyLargeHeavy", "bodyXLargeHeavy")
FUND_LABEL_KEYWORDS = (
    "expense",
    "ratio",
    "nav",
    "sip",
    "aum",
    "fund size",
    "benchmark",
    "exit load",
    "rating",
    "risk",
    "minimum",
    "min.",
    "launch",
    "incorporation",
    "phone",
    "email",
    "website",
    "address",
    "custodian",
    "registrar",
    "stamp duty",
    "tax",
    "lock-in",
    "lock in",
)


def _is_fund_label(label: str) -> bool:
    lowered = label.lower()
    return any(keyword in lowered for keyword in FUND_LABEL_KEYWORDS)


MAX_LABEL_LENGTH = 80


def _is_label_tag(tag: Tag) -> bool:
    class_value = tag.get("class") or []
    class_text = " ".join(class_value) if isinstance(class_value, list) else str(class_value)
    return any(marker in class_text for marker in LABEL_CLASS_MARKERS)


def _is_value_tag(tag: Tag) -> bool:
    class_value = tag.get("class") or []
    class_text = " ".join(class_value) if isinstance(class_value, list) else str(class_value)
    return any(marker in class_text for marker in VALUE_CLASS_MARKERS)


def _find_value_tag(label: Tag) -> Tag | None:
    for sibling in label.next_siblings:
        if isinstance(sibling, Tag) and _is_value_tag(sibling):
            return sibling

    if label.parent is not None:
        for sibling in label.parent.find_all(_is_value_tag, recursive=False):
            if sibling is not label:
                return sibling
        value_tag = label.parent.find(_is_value_tag)
        if value_tag is not None and value_tag is not label:
            return value_tag

    return None


def _extract_label_value_pairs(soup: BeautifulSoup) -> dict[str, str]:
    pairs: dict[str, str] = {}

    for label in soup.find_all(["span", "div"]):
        if not isinstance(label, Tag) or not _is_label_tag(label):
            continue
        label_text = _normalize_whitespace(label.get_text(" ", strip=True))
        if (
            not label_text
            or len(label_text) > MAX_LABEL_LENGTH
            or not _is_fund_label(label_text)
            or label_text.lower() in {"name", "sector", "instruments", "assets"}
        ):
            continue

        value_tag = _find_value_tag(label)
        if value_tag is None:
            continue

        value_text = _normalize_whitespace(value_tag.get_text(" ", strip=True))
        if len(label_text) > len(value_text) * 2 and len(label_text) > 30:
            continue
        if value_text and label_text not in pairs:
            pairs[label_text] = value_text

    return pairs


def _find_table_title(table: Tag) -> str | None:
    for heading in table.find_all_previous(["h2", "h3", "h4"], limit=3):
        title = _normalize_heading(heading.get_text(strip=True))
        if title and not _should_skip_section(title):
            return title
    return None


def _should_skip_table(table: Tag, title: str | None) -> bool:
    text = table.get_text(" ", strip=True).lower()
    title_lower = (title or "").lower()
    markers = SKIP_TABLE_MARKERS + tuple(SKIP_SECTION_HEADINGS)
    return any(marker in text or marker in title_lower for marker in markers)


def _extract_tables(soup: BeautifulSoup) -> list[ParsedTable]:
    tables: list[ParsedTable] = []

    for table in soup.find_all("table"):
        title = _find_table_title(table)
        if _should_skip_table(table, title):
            continue

        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [
                _normalize_whitespace(cell.get_text(" ", strip=True))
                for cell in tr.find_all(["th", "td"])
            ]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(cells)

        if not rows:
            continue

        headers = tuple(rows[0]) if rows else tuple()
        body_rows = tuple(tuple(row) for row in rows[1:]) if len(rows) > 1 else tuple()
        tables.append(ParsedTable(title=title, headers=headers, rows=body_rows))

    return tables


def _extract_sections(soup: BeautifulSoup) -> dict[str, str]:
    sections: dict[str, str] = {}

    for heading in soup.find_all(["h2", "h3", "h4"]):
        title = _normalize_heading(heading.get_text(strip=True))
        if not title or _should_skip_section(title):
            continue

        content_parts: list[str] = []
        for sibling in heading.find_next_siblings():
            if isinstance(sibling, Tag) and sibling.name in {"h2", "h3", "h4"}:
                break
            if isinstance(sibling, Tag) and sibling.name == "table":
                break
            text = _normalize_whitespace(sibling.get_text(" ", strip=True))
            if text:
                content_parts.append(text)

        if not content_parts:
            continue

        content = _normalize_whitespace(" ".join(content_parts))
        if len(content) < 20 and title.lower().startswith("about"):
            continue
        if title in sections:
            if content not in sections[title]:
                sections[title] = _normalize_whitespace(f"{sections[title]} {content}")
        else:
            sections[title] = content

    return sections


def _readability_text(html: str) -> str:
    summary = Document(html).summary()
    soup = BeautifulSoup(summary, "html.parser")
    return _normalize_whitespace(soup.get_text("\n", strip=True))


def parse_html(
    html: str,
    *,
    scheme_name: str | None = None,
    scheme_category: str | None = None,
) -> ParsedSchemePage:
    """
    Parse Groww scheme HTML into structured fields and cleaned text.

    Uses BeautifulSoup to strip boilerplate and extract fund metadata, sections,
    and tables. Readability supplements narrative content such as exit load and tax.
    """
    soup = BeautifulSoup(html, "html.parser")
    _remove_boilerplate(soup)

    fund_name = _extract_fund_name(soup, scheme_name)
    category = _extract_category(soup, fund_name, scheme_category)
    label_values = _extract_label_value_pairs(soup)
    sections = _extract_sections(soup)
    tables = _extract_tables(soup)
    readability = _readability_text(str(soup))

    overview_lines = [f"{label}: {value}" for label, value in label_values.items()]
    section_lines = [f"{heading}\n{content}" for heading, content in sections.items()]
    table_lines = [table.to_text() for table in tables if table.to_text()]
    combined_parts = overview_lines + section_lines + table_lines
    if readability:
        combined_parts.append(readability)

    text = _normalize_whitespace("\n\n".join(part for part in combined_parts if part))

    return ParsedSchemePage(
        fund_name=fund_name,
        category=category,
        sections=sections,
        tables=tables,
        label_values=label_values,
        text=text,
    )


def parse_raw_html_file(
    raw_path: Path,
    *,
    scheme_name: str | None = None,
    scheme_category: str | None = None,
) -> ParsedSchemePage:
    """Parse a saved raw HTML file from ``data/raw/``."""
    html = raw_path.read_text(encoding="utf-8")
    return parse_html(
        html,
        scheme_name=scheme_name,
        scheme_category=scheme_category,
    )


def write_parsed_outputs(
    parsed: ParsedSchemePage,
    *,
    slug: str,
    source_url: str | None = None,
    processed_dir: Path | None = None,
) -> dict[str, Path]:
    """
    Write human-readable and structured review files for Phase 1.2 QA.

    Creates ``data/processed/{slug}.txt`` and ``data/processed/{slug}.json``.
    """
    processed_dir = processed_dir or DEFAULT_PROCESSED_DIR
    processed_dir.mkdir(parents=True, exist_ok=True)

    txt_path = processed_dir / f"{slug}.txt"
    json_path = processed_dir / f"{slug}.json"

    txt_path.write_text(parsed.to_processed_text(), encoding="utf-8")
    review_payload = parsed.to_review_dict(slug=slug, source_url=source_url)
    json_path.write_text(
        json.dumps(review_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {"txt": txt_path, "json": json_path}


def write_review_index(
    parsed_pages: list[tuple[SchemeSource, ParsedSchemePage]],
    *,
    processed_dir: Path | None = None,
) -> Path:
    """Write ``data/processed/index.json`` summarizing all parsed schemes."""
    processed_dir = processed_dir or DEFAULT_PROCESSED_DIR
    processed_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    for scheme, parsed in parsed_pages:
        slug = url_to_slug(scheme.url)
        entries.append(
            {
                "slug": slug,
                "scheme_name": scheme.name,
                "category": parsed.category or scheme.category,
                "source_url": scheme.url,
                "files": {
                    "txt": f"{slug}.txt",
                    "json": f"{slug}.json",
                },
                "label_count": len(parsed.label_values),
                "section_count": len(parsed.sections),
                "table_count": len(parsed.tables),
            }
        )

    index_path = processed_dir / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "scheme_count": len(entries),
                "schemes": entries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return index_path


def write_processed_page(
    parsed: ParsedSchemePage,
    *,
    slug: str,
    source_url: str | None = None,
    processed_dir: Path | None = None,
) -> Path:
    """Write parsed page review files; returns the plain-text output path."""
    outputs = write_parsed_outputs(
        parsed,
        slug=slug,
        source_url=source_url,
        processed_dir=processed_dir,
    )
    return outputs["txt"]


def parse_scheme_source(
    scheme: SchemeSource,
    *,
    raw_dir: Path | None = None,
    processed_dir: Path | None = None,
    write_processed: bool = True,
) -> ParsedSchemePage:
    """Parse one scheme's raw HTML using metadata from the source registry."""
    raw_dir = raw_dir or DEFAULT_RAW_DIR
    slug = url_to_slug(scheme.url)
    raw_path = raw_dir / f"{slug}.html"
    if not raw_path.is_file():
        raise FileNotFoundError(f"Raw HTML not found: {raw_path}")

    parsed = parse_raw_html_file(
        raw_path,
        scheme_name=scheme.name,
        scheme_category=scheme.category,
    )
    if write_processed:
        write_parsed_outputs(
            parsed,
            slug=slug,
            source_url=scheme.url,
            processed_dir=processed_dir,
        )
    return parsed


def parse_all_schemes(
    *,
    raw_dir: Path | None = None,
    processed_dir: Path | None = None,
    write_processed: bool = True,
) -> list[ParsedSchemePage]:
    """Parse all schemes that have raw HTML snapshots available."""
    results: list[ParsedSchemePage] = []
    review_entries: list[tuple[SchemeSource, ParsedSchemePage]] = []
    for scheme in load_sources():
        slug = url_to_slug(scheme.url)
        raw_path = (raw_dir or DEFAULT_RAW_DIR) / f"{slug}.html"
        if not raw_path.is_file():
            logger.warning("Skipping %s — raw HTML missing at %s", scheme.name, raw_path)
            continue
        parsed = parse_scheme_source(
            scheme,
            raw_dir=raw_dir,
            processed_dir=processed_dir,
            write_processed=write_processed,
        )
        results.append(parsed)
        review_entries.append((scheme, parsed))

    if write_processed and review_entries:
        write_review_index(review_entries, processed_dir=processed_dir)

    return results


def main() -> None:
    """CLI entry point: parse available raw HTML into ``data/processed/``."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parsed_pages = parse_all_schemes()
    logger.info(
        "Parsed %s scheme page(s). Review files in %s",
        len(parsed_pages),
        DEFAULT_PROCESSED_DIR,
    )


if __name__ == "__main__":
    main()
