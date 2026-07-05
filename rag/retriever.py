"""Vector retriever with scheme filtering and context assembly."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ingestion.fetcher import SchemeSource, load_sources
from ingestion.indexer import (
    BGEEmbedder,
    COLLECTION_NAME,
    DEFAULT_VECTORSTORE_DIR,
)

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5
MAX_TOP_K = 8
DEFAULT_SCORE_THRESHOLD = 0.5
FACTUAL_CONTENT_TYPE = "factual"


def _build_match_patterns(schemes: list[SchemeSource]) -> list[tuple[str, str]]:
    patterns: list[tuple[str, str]] = []
    for scheme in schemes:
        patterns.append((scheme.name.lower(), scheme.name))
        for alias in scheme.aliases:
            patterns.append((alias.lower(), scheme.name))
        if "—" in scheme.category:
            category_hint = scheme.category.split("—", 1)[1].strip().lower()
            patterns.append((category_hint, scheme.name))
    patterns.sort(key=lambda item: len(item[0]), reverse=True)
    return patterns


class IndexNotReadyError(FileNotFoundError):
    """Raised when the vector index has not been built yet."""


@dataclass(frozen=True)
class RetrievedChunk:
    """One chunk returned from vector search."""

    chunk_id: str
    text: str
    score: float
    scheme_name: str
    scheme_category: str
    section: str
    content_type: str
    source_url: str
    last_fetched_at: str


@dataclass(frozen=True)
class RetrievalResult:
    """Outcome of a factual retrieval request."""

    query: str
    resolved_scheme: str | None
    chunks: tuple[RetrievedChunk, ...]
    context: str
    sufficient: bool


class SchemeResolver:
    """Map query text to canonical scheme names via ``sources.yaml`` aliases."""

    def __init__(self, schemes: list[SchemeSource] | None = None) -> None:
        self._schemes = schemes or load_sources()
        self._patterns = _build_match_patterns(self._schemes)

    def resolve(self, query: str) -> str | None:
        """Return the canonical scheme name mentioned in *query*, if any."""
        normalized = query.lower()
        for pattern, scheme_name in self._patterns:
            if pattern in normalized:
                return scheme_name
        return None

    def get_scheme(self, scheme_name: str) -> SchemeSource | None:
        for scheme in self._schemes:
            if scheme.name == scheme_name:
                return scheme
        return None


def load_index_manifest(vectorstore_dir: Path) -> dict[str, Any]:
    manifest_path = vectorstore_dir / "index_manifest.json"
    if not manifest_path.is_file():
        raise IndexNotReadyError(
            f"Vector index not found at {manifest_path}. "
            "Run: python scripts/build_index.py --index"
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def load_chroma_collection(vectorstore_dir: Path, collection_name: str = COLLECTION_NAME):
    import chromadb

    load_index_manifest(vectorstore_dir)
    client = chromadb.PersistentClient(path=str(vectorstore_dir))
    return client.get_collection(collection_name)


def build_metadata_filter(
    *,
    scheme_name: str | None,
    content_type: str | None,
) -> dict[str, Any] | None:
    """Build a Chroma ``where`` filter for scheme and content type."""
    clauses: list[dict[str, Any]] = []
    if scheme_name:
        clauses.append({"scheme_name": scheme_name})
    if content_type:
        clauses.append({"content_type": content_type})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def distance_to_score(distance: float) -> float:
    """Convert Chroma cosine distance to similarity (both vectors L2-normalized)."""
    return 1.0 - distance


def deduplicate_by_section(
    chunks: list[RetrievedChunk],
    *,
    top_k: int,
) -> list[RetrievedChunk]:
    """Keep the highest-scoring chunk per ``section`` slug."""
    best_by_section: dict[str, RetrievedChunk] = {}
    for chunk in sorted(chunks, key=lambda item: item.score, reverse=True):
        if chunk.section not in best_by_section:
            best_by_section[chunk.section] = chunk
    ranked = sorted(best_by_section.values(), key=lambda item: item.score, reverse=True)
    return ranked[:top_k]


def assemble_context(chunks: list[RetrievedChunk]) -> str:
    """Concatenate retrieved chunk bodies for the Groq prompt."""
    return "\n\n".join(chunk.text for chunk in chunks)


def _records_to_chunks(
    *,
    ids: list[str],
    documents: list[str],
    metadatas: list[dict[str, Any]],
    distances: list[float],
) -> list[RetrievedChunk]:
    chunks: list[RetrievedChunk] = []
    for index, chunk_id in enumerate(ids):
        metadata = metadatas[index]
        chunks.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                text=documents[index],
                score=distance_to_score(distances[index]),
                scheme_name=metadata["scheme_name"],
                scheme_category=metadata["scheme_category"],
                section=metadata["section"],
                content_type=metadata["content_type"],
                source_url=metadata["source_url"],
                last_fetched_at=metadata["last_fetched_at"],
            )
        )
    return chunks


class Retriever:
    """
    Metadata-filtered BGE retrieval over the HDFC fund Chroma collection.

    Pipeline: resolve scheme → filter ``content_type`` → embed query with BGE
    prefix → cosine top-k → deduplicate by ``section`` → assemble context.
    """

    def __init__(
        self,
        *,
        vectorstore_dir: Path | None = None,
        embedder: BGEEmbedder | None = None,
        resolver: SchemeResolver | None = None,
        collection: Any | None = None,
        top_k: int = DEFAULT_TOP_K,
        max_top_k: int = MAX_TOP_K,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    ) -> None:
        self.vectorstore_dir = vectorstore_dir or DEFAULT_VECTORSTORE_DIR
        self.embedder = embedder or BGEEmbedder()
        self.resolver = resolver or SchemeResolver()
        self._collection = collection
        self.top_k = top_k
        self.max_top_k = max_top_k
        self.score_threshold = score_threshold

    def reset_collection(self) -> None:
        """Drop cached Chroma handle (e.g. after reindex)."""
        self._collection = None

    @property
    def collection(self) -> Any:
        if self._collection is None:
            self._collection = load_chroma_collection(self.vectorstore_dir)
        return self._collection

    def retrieve(
        self,
        query: str,
        *,
        content_type: str = FACTUAL_CONTENT_TYPE,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> RetrievalResult:
        """Retrieve factual chunks for a user query."""
        effective_top_k = min(max(top_k or self.top_k, 1), self.max_top_k)
        threshold = self.score_threshold if score_threshold is None else score_threshold
        resolved_scheme = self.resolver.resolve(query)
        where = build_metadata_filter(
            scheme_name=resolved_scheme,
            content_type=content_type,
        )

        query_embedding = self.embedder.encode_query(query)
        raw_count = min(effective_top_k * 3, 60)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=raw_count,
            where=where,
            include=["metadatas", "documents", "distances"],
        )

        if not results["ids"] or not results["ids"][0]:
            return RetrievalResult(
                query=query,
                resolved_scheme=resolved_scheme,
                chunks=(),
                context="",
                sufficient=False,
            )

        raw_chunks = _records_to_chunks(
            ids=results["ids"][0],
            documents=results["documents"][0],
            metadatas=results["metadatas"][0],
            distances=results["distances"][0],
        )
        deduped = deduplicate_by_section(raw_chunks, top_k=effective_top_k)
        passing = [chunk for chunk in deduped if chunk.score >= threshold]
        context = assemble_context(passing)

        return RetrievalResult(
            query=query,
            resolved_scheme=resolved_scheme,
            chunks=tuple(passing),
            context=context,
            sufficient=bool(passing),
        )


def retrieve(query: str, **kwargs: Any) -> RetrievalResult:
    """Convenience wrapper using a process-wide default retriever instance."""
    return get_retriever().retrieve(query, **kwargs)


_default_retriever: Retriever | None = None


def get_retriever() -> Retriever:
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = Retriever()
    return _default_retriever
