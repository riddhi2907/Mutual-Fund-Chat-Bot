"""BGE embedding and ChromaDB vector index builder."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ingestion.chunker import DEFAULT_CHUNKS_PATH

logger = logging.getLogger(__name__)

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VECTORSTORE_DIR = PROJECT_ROOT / "data" / "vectorstore"
DEFAULT_BGE_MODEL = "BAAI/bge-small-en-v1.5"
QUERY_INSTRUCTION_PREFIX = "Represent this sentence for searching relevant passages: "
COLLECTION_NAME = "hdfc_funds"
DEFAULT_BATCH_SIZE = 32


def get_bge_model_name() -> str:
    """Return the BGE model name from ``BGE_MODEL_NAME`` or the project default."""
    return os.getenv("BGE_MODEL_NAME", DEFAULT_BGE_MODEL)


def _to_embedding_list(embeddings: Any) -> list[list[float]] | list[float]:
    """Normalize SentenceTransformer output to plain Python lists."""
    if hasattr(embeddings, "tolist"):
        return embeddings.tolist()
    return embeddings


class BGEEmbedder:
    """Local BGE encoder with separate document and query encoding rules."""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or get_bge_model_name()
        self._model: Any | None = None

    @property
    def model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading BGE model: %s", self.model_name)
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def encode_documents(
        self,
        texts: list[str],
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> list[list[float]]:
        """Embed chunk bodies as-is (no instruction prefix)."""
        if not texts:
            return []

        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > batch_size,
        )
        return _to_embedding_list(embeddings)

    def encode_query(self, query: str) -> list[float]:
        """Embed a user query with the BGE retrieval instruction prefix."""
        prefixed = QUERY_INSTRUCTION_PREFIX + query
        embedding = self.model.encode(
            prefixed,
            normalize_embeddings=True,
        )
        return _to_embedding_list(embedding)


def load_chunks_from_jsonl(chunks_path: Path) -> list[dict[str, Any]]:
    """Load chunk records from a JSONL file."""
    if not chunks_path.is_file():
        raise FileNotFoundError(f"Chunks file not found: {chunks_path}")

    chunks: list[dict[str, Any]] = []
    with chunks_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                chunks.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {line_number} of {chunks_path}: {exc.msg}"
                ) from exc
    return chunks


def chunk_to_metadata(chunk: dict[str, Any]) -> dict[str, Any]:
    """Map a chunk record to ChromaDB-compatible metadata."""
    return {
        "scheme_name": chunk["scheme_name"],
        "scheme_category": chunk["scheme_category"],
        "section": chunk["section"],
        "content_type": chunk["content_type"],
        "source_url": chunk["source_url"],
        "source_domain": chunk["source_domain"],
        "chunk_id": chunk["chunk_id"],
        "token_count": int(chunk["token_count"]),
        "last_fetched_at": chunk["last_fetched_at"],
    }


def write_index_manifest(
    *,
    vectorstore_dir: Path,
    bge_model_name: str,
    chunk_ids: list[str],
    collection_name: str = COLLECTION_NAME,
    embedded_at: str | None = None,
) -> Path:
    """Persist index metadata beside the ChromaDB store."""
    manifest_path = vectorstore_dir / "index_manifest.json"
    manifest = {
        "bge_model_name": bge_model_name,
        "collection_name": collection_name,
        "chunk_count": len(chunk_ids),
        "embedded_at": embedded_at
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "chunk_ids": chunk_ids,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def build_vector_index(
    *,
    chunks_path: Path | None = None,
    vectorstore_dir: Path | None = None,
    embedder: BGEEmbedder | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    collection_name: str = COLLECTION_NAME,
) -> dict[str, Any]:
    """
    Batch-embed ``chunks.jsonl`` and upsert vectors into a persistent ChromaDB store.

    Returns the index manifest dict written to ``index_manifest.json``.
    """
    import chromadb

    resolved_chunks_path = chunks_path or DEFAULT_CHUNKS_PATH
    resolved_vectorstore_dir = vectorstore_dir or DEFAULT_VECTORSTORE_DIR

    chunks = load_chunks_from_jsonl(resolved_chunks_path)
    if not chunks:
        raise ValueError(f"No chunks found in {resolved_chunks_path}")

    encoder = embedder or BGEEmbedder()
    texts = [chunk["text"] for chunk in chunks]
    embeddings = encoder.encode_documents(texts, batch_size=batch_size)
    ids = [chunk["chunk_id"] for chunk in chunks]
    metadatas = [chunk_to_metadata(chunk) for chunk in chunks]

    resolved_vectorstore_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(resolved_vectorstore_dir))

    try:
        client.delete_collection(collection_name)
    except (ValueError, chromadb.errors.NotFoundError):
        pass

    collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )

    embedded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest_path = write_index_manifest(
        vectorstore_dir=resolved_vectorstore_dir,
        bge_model_name=encoder.model_name,
        chunk_ids=ids,
        collection_name=collection_name,
        embedded_at=embedded_at,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    logger.info(
        "Indexed %s chunk(s) into %s (collection=%s)",
        len(chunks),
        resolved_vectorstore_dir,
        collection_name,
    )
    return manifest
