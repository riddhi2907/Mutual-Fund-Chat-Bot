"""Inspect chunk embeddings stored in the ChromaDB vector index."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ingestion.indexer import (  # noqa: E402
    BGEEmbedder,
    COLLECTION_NAME,
    DEFAULT_VECTORSTORE_DIR,
)


def load_manifest(vectorstore_dir: Path) -> dict:
    manifest_path = vectorstore_dir / "index_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Index manifest not found at {manifest_path}. "
            "Run: python -c \"from ingestion.indexer import build_vector_index; build_vector_index()\""
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def load_collection(vectorstore_dir: Path):
    import chromadb

    client = chromadb.PersistentClient(path=str(vectorstore_dir))
    return client.get_collection(COLLECTION_NAME)


def embedding_stats(vector: list[float]) -> dict:
    """Summary stats for a single embedding vector."""
    values = [float(value) for value in vector]
    l2_norm = math.sqrt(sum(value * value for value in values))
    return {
        "dimensions": len(values),
        "l2_norm": round(l2_norm, 6),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
        "preview": [round(value, 6) for value in values[:8]],
    }


def cosine_similarity(a: list[float], b: list[float]) -> float:
    return sum(float(x) * float(y) for x, y in zip(a, b))


def format_chunk_line(
    chunk_id: str,
    metadata: dict,
    vector: list[float],
    *,
    verbose: bool,
) -> str:
    scheme = metadata.get("scheme_name", "?")
    section = metadata.get("section", "?")
    stats = embedding_stats(vector)
    line = (
        f"{chunk_id}\n"
        f"  scheme: {scheme}\n"
        f"  section: {section} | content_type: {metadata.get('content_type', '?')}\n"
        f"  dims: {stats['dimensions']} | L2 norm: {stats['l2_norm']} | "
        f"range: [{stats['min']}, {stats['max']}]\n"
        f"  preview (first 8): {stats['preview']}"
    )
    if verbose:
        text = metadata.get("document") or ""
        line += f"\n  text:\n    {text.replace(chr(10), chr(10) + '    ')}"
        line += f"\n  full vector: {[float(v) for v in vector]}"
    return line


def attach_documents(records: dict) -> list[dict]:
    rows = []
    for index, chunk_id in enumerate(records["ids"]):
        metadata = dict(records["metadatas"][index])
        if records.get("documents"):
            metadata["document"] = records["documents"][index]
        rows.append(
            {
                "chunk_id": chunk_id,
                "metadata": metadata,
                "embedding": records["embeddings"][index],
            }
        )
    return rows


def print_summary(manifest: dict, rows: list[dict]) -> None:
    print("=== Vector index summary ===")
    print(f"Model:        {manifest.get('bge_model_name')}")
    print(f"Collection:   {manifest.get('collection_name', COLLECTION_NAME)}")
    print(f"Chunk count:  {manifest.get('chunk_count', len(rows))}")
    print(f"Embedded at:  {manifest.get('embedded_at')}")
    if rows:
        stats = embedding_stats(rows[0]["embedding"])
        print(f"Vector dims:  {stats['dimensions']}")
    print()


def run_list(
    *,
    vectorstore_dir: Path,
    limit: int | None,
    verbose: bool,
    scheme: str | None,
    section: str | None,
) -> None:
    manifest = load_manifest(vectorstore_dir)
    collection = load_collection(vectorstore_dir)
    records = collection.get(include=["embeddings", "metadatas", "documents"])
    rows = attach_documents(records)

    if scheme:
        needle = scheme.lower()
        rows = [
            row
            for row in rows
            if needle in row["metadata"].get("scheme_name", "").lower()
        ]
    if section:
        rows = [row for row in rows if row["metadata"].get("section") == section]

    rows.sort(key=lambda row: row["chunk_id"])
    if limit is not None:
        rows = rows[:limit]

    print_summary(manifest, attach_documents(records))
    print(f"=== Chunks ({len(rows)} shown) ===\n")
    for row in rows:
        print(
            format_chunk_line(
                row["chunk_id"],
                row["metadata"],
                row["embedding"],
                verbose=verbose,
            )
        )
        print()


def run_chunk(*, vectorstore_dir: Path, chunk_id: str, verbose: bool) -> None:
    manifest = load_manifest(vectorstore_dir)
    collection = load_collection(vectorstore_dir)
    records = collection.get(
        ids=[chunk_id],
        include=["embeddings", "metadatas", "documents"],
    )
    if not records["ids"]:
        raise SystemExit(f"Chunk not found: {chunk_id}")

    row = attach_documents(records)[0]
    print_summary(manifest, [row])
    print("=== Chunk detail ===\n")
    print(
        format_chunk_line(
            row["chunk_id"],
            row["metadata"],
            row["embedding"],
            verbose=True,
        )
    )


def run_query(
    *,
    vectorstore_dir: Path,
    query: str,
    top_k: int,
    scheme: str | None,
) -> None:
    manifest = load_manifest(vectorstore_dir)
    collection = load_collection(vectorstore_dir)
    records = collection.get(include=["embeddings", "metadatas", "documents"])
    rows = attach_documents(records)

    embedder = BGEEmbedder(model_name=manifest.get("bge_model_name"))
    query_vector = embedder.encode_query(query)

    if scheme:
        needle = scheme.lower()
        rows = [
            row
            for row in rows
            if needle in row["metadata"].get("scheme_name", "").lower()
        ]

    scored = []
    for row in rows:
        score = cosine_similarity(query_vector, row["embedding"])
        scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)

    print_summary(manifest, rows)
    print(f'=== Query: "{query}" ===')
    print(f"Top {min(top_k, len(scored))} by cosine similarity\n")
    for score, row in scored[:top_k]:
        meta = row["metadata"]
        print(
            f"score={score:.4f} | {row['chunk_id']}\n"
            f"  {meta.get('scheme_name')} | section={meta.get('section')}\n"
            f"  {meta.get('document', '').splitlines()[0]}"
        )
        print()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="View chunk embeddings from the ChromaDB vector store.",
    )
    parser.add_argument(
        "--vectorstore-dir",
        type=Path,
        default=DEFAULT_VECTORSTORE_DIR,
        help=f"Path to ChromaDB store (default: {DEFAULT_VECTORSTORE_DIR})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Max chunks to list (default: 5; use 0 for all)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show chunk text and full embedding vectors",
    )
    parser.add_argument(
        "--scheme",
        help="Filter by scheme name substring (case-insensitive)",
    )
    parser.add_argument(
        "--section",
        help="Filter by section slug (e.g. expense_ratio, exit_load)",
    )
    parser.add_argument(
        "--chunk-id",
        help="Show one chunk by id",
    )
    parser.add_argument(
        "--query",
        help="Embed a query and rank chunks by cosine similarity",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of results for --query (default: 5)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    limit = None if args.limit == 0 else args.limit

    try:
        if args.chunk_id:
            run_chunk(
                vectorstore_dir=args.vectorstore_dir,
                chunk_id=args.chunk_id,
                verbose=args.verbose,
            )
        elif args.query:
            run_query(
                vectorstore_dir=args.vectorstore_dir,
                query=args.query,
                top_k=args.top_k,
                scheme=args.scheme,
            )
        else:
            run_list(
                vectorstore_dir=args.vectorstore_dir,
                limit=limit,
                verbose=args.verbose,
                scheme=args.scheme,
                section=args.section,
            )
        return 0
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
