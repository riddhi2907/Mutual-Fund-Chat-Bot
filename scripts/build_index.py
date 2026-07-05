"""Orchestrate fetch → parse → chunk → index pipeline for the Groww corpus."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ingestion.chunker import DEFAULT_CHUNKS_PATH, build_chunks
from ingestion.fetcher import DEFAULT_RAW_DIR, FetchError, fetch_all_schemes
from ingestion.indexer import DEFAULT_VECTORSTORE_DIR, build_vector_index
from ingestion.parser import DEFAULT_PROCESSED_DIR, parse_all_schemes

logger = logging.getLogger(__name__)


def run_fetch(*, raw_dir: Path | None = None) -> int:
    """Fetch all Groww scheme pages into ``data/raw/``."""
    results = fetch_all_schemes(raw_dir=raw_dir)
    cached = sum(1 for result in results if result.from_cache)
    fresh = len(results) - cached
    logger.info(
        "Fetched %s scheme page(s): %s fresh, %s from cache",
        len(results),
        fresh,
        cached,
    )
    return len(results)


def run_parse(
    *,
    raw_dir: Path | None = None,
    processed_dir: Path | None = None,
) -> int:
    """Parse raw HTML into ``data/processed/`` review files."""
    parsed_pages = parse_all_schemes(
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        write_processed=True,
    )
    logger.info(
        "Parsed %s scheme page(s). Review files in %s",
        len(parsed_pages),
        processed_dir or DEFAULT_PROCESSED_DIR,
    )
    return len(parsed_pages)


def run_chunk(
    *,
    processed_dir: Path | None = None,
    chunks_path: Path | None = None,
) -> int:
    """Chunk processed JSON files into ``data/chunks/chunks.jsonl``."""
    output_path = build_chunks(
        processed_dir=processed_dir,
        output_path=chunks_path,
    )
    return sum(1 for _ in output_path.open(encoding="utf-8"))


def run_index(
    *,
    chunks_path: Path | None = None,
    vectorstore_dir: Path | None = None,
) -> int:
    """Embed chunks and persist the ChromaDB vector index."""
    manifest = build_vector_index(
        chunks_path=chunks_path,
        vectorstore_dir=vectorstore_dir,
    )
    logger.info(
        "Built vector index with %s chunk(s) at %s",
        manifest["chunk_count"],
        vectorstore_dir or DEFAULT_VECTORSTORE_DIR,
    )
    return int(manifest["chunk_count"])


def run_ingestion_pipeline(
    *,
    fetch: bool = True,
    parse: bool = True,
    chunk: bool = True,
    raw_dir: Path | None = None,
    processed_dir: Path | None = None,
    chunks_path: Path | None = None,
) -> dict[str, int]:
    """
    Run fetch, parse, and/or chunk steps.

    Returns counts keyed by ``fetched``, ``parsed``, and ``chunked``.
    """
    counts: dict[str, int] = {}

    if fetch:
        counts["fetched"] = run_fetch(raw_dir=raw_dir)
    if parse:
        counts["parsed"] = run_parse(raw_dir=raw_dir, processed_dir=processed_dir)
    if chunk:
        counts["chunked"] = run_chunk(
            processed_dir=processed_dir,
            chunks_path=chunks_path,
        )

    return counts


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the Groww corpus: fetch, parse, chunk, and (optionally) index.",
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Fetch Groww HTML pages into data/raw/ only.",
    )
    parser.add_argument(
        "--chunk-only",
        action="store_true",
        help="Chunk existing data/processed/*.json into data/chunks/chunks.jsonl only.",
    )
    parser.add_argument(
        "--index",
        action="store_true",
        help="Embed chunks.jsonl into data/vectorstore/ (ChromaDB + BGE).",
    )
    parser.add_argument(
        "--vectorstore-dir",
        type=Path,
        default=DEFAULT_VECTORSTORE_DIR,
        help=f"Output directory for ChromaDB (default: {DEFAULT_VECTORSTORE_DIR})",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help=f"Directory for raw HTML (default: {DEFAULT_RAW_DIR})",
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=DEFAULT_PROCESSED_DIR,
        help=f"Directory for processed JSON/txt (default: {DEFAULT_PROCESSED_DIR})",
    )
    parser.add_argument(
        "--chunks-path",
        type=Path,
        default=DEFAULT_CHUNKS_PATH,
        help=f"Output JSONL path for chunks (default: {DEFAULT_CHUNKS_PATH})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    exclusive = sum([args.fetch_only, args.chunk_only, args.index])
    if exclusive > 1:
        parser.error("Use only one of --fetch-only, --chunk-only, or --index.")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    try:
        if args.fetch_only:
            run_fetch(raw_dir=args.raw_dir)
            return 0

        if args.chunk_only:
            run_chunk(processed_dir=args.processed_dir, chunks_path=args.chunks_path)
            return 0

        if args.index:
            run_index(
                chunks_path=args.chunks_path,
                vectorstore_dir=args.vectorstore_dir,
            )
            return 0

        run_ingestion_pipeline(
            fetch=True,
            parse=True,
            chunk=True,
            raw_dir=args.raw_dir,
            processed_dir=args.processed_dir,
            chunks_path=args.chunks_path,
        )
        return 0
    except FetchError as exc:
        logger.error("%s", exc)
        return 1
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
