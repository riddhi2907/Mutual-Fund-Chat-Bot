"""Unit tests for BGE embedding and ChromaDB index builder (Phase 2.1–2.2)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from ingestion.indexer import (
    BGEEmbedder,
    COLLECTION_NAME,
    QUERY_INSTRUCTION_PREFIX,
    build_vector_index,
    chunk_to_metadata,
    get_bge_model_name,
    load_chunks_from_jsonl,
)


@pytest.fixture
def sample_chunks() -> list[dict]:
    return [
        {
            "chunk_id": "scheme-a-expense_ratio-001",
            "scheme_name": "HDFC Scheme A",
            "scheme_category": "Equity — Large Cap",
            "source_url": "https://groww.in/mutual-funds/scheme-a",
            "source_domain": "groww.in",
            "section": "expense_ratio",
            "content_type": "factual",
            "text": "Fund: HDFC Scheme A\nCategory: Equity — Large Cap\nExpense ratio: 1.00%",
            "last_fetched_at": "2026-07-05T17:10:32Z",
            "token_count": 20,
        },
        {
            "chunk_id": "scheme-a-returns_rankings-001",
            "scheme_name": "HDFC Scheme A",
            "scheme_category": "Equity — Large Cap",
            "source_url": "https://groww.in/mutual-funds/scheme-a",
            "source_domain": "groww.in",
            "section": "returns_rankings",
            "content_type": "performance",
            "text": "Fund: HDFC Scheme A\nCategory: Equity — Large Cap\nReturns and rankings:\nFund returns | +10%",
            "last_fetched_at": "2026-07-05T17:10:32Z",
            "token_count": 25,
        },
    ]


@pytest.fixture
def chunks_jsonl(tmp_path: Path, sample_chunks: list[dict]) -> Path:
    path = tmp_path / "chunks.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for chunk in sample_chunks:
            handle.write(json.dumps(chunk) + "\n")
    return path


class FakeModel:
    def __init__(self) -> None:
        self.encode_calls: list[dict] = []

    def encode(self, inputs, **kwargs):
        self.encode_calls.append({"inputs": inputs, "kwargs": kwargs})
        if isinstance(inputs, str):
            return [0.1, 0.2, 0.3]
        return [[float(index), 0.5, 0.5] for index, _ in enumerate(inputs)]


def test_get_bge_model_name_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BGE_MODEL_NAME", raising=False)
    assert get_bge_model_name() == "BAAI/bge-small-en-v1.5"


def test_get_bge_model_name_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BGE_MODEL_NAME", "custom/model")
    assert get_bge_model_name() == "custom/model"


def test_encode_documents_without_prefix() -> None:
    embedder = BGEEmbedder(model_name="test-model")
    fake_model = FakeModel()
    embedder._model = fake_model

    texts = ["doc one", "doc two"]
    embeddings = embedder.encode_documents(texts, batch_size=16)

    assert embeddings == [[0.0, 0.5, 0.5], [1.0, 0.5, 0.5]]
    assert fake_model.encode_calls[0]["inputs"] == texts
    assert fake_model.encode_calls[0]["kwargs"]["normalize_embeddings"] is True
    assert fake_model.encode_calls[0]["kwargs"]["batch_size"] == 16


def test_encode_query_uses_instruction_prefix() -> None:
    embedder = BGEEmbedder(model_name="test-model")
    fake_model = FakeModel()
    embedder._model = fake_model

    embedding = embedder.encode_query("expense ratio mid cap")

    assert embedding == [0.1, 0.2, 0.3]
    assert fake_model.encode_calls[0]["inputs"] == (
        QUERY_INSTRUCTION_PREFIX + "expense ratio mid cap"
    )
    assert fake_model.encode_calls[0]["kwargs"]["normalize_embeddings"] is True


def test_load_chunks_from_jsonl(chunks_jsonl: Path, sample_chunks: list[dict]) -> None:
    loaded = load_chunks_from_jsonl(chunks_jsonl)
    assert loaded == sample_chunks


def test_load_chunks_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_chunks_from_jsonl(tmp_path / "missing.jsonl")


def test_chunk_to_metadata(sample_chunks: list[dict]) -> None:
    metadata = chunk_to_metadata(sample_chunks[0])
    assert metadata["scheme_name"] == "HDFC Scheme A"
    assert metadata["section"] == "expense_ratio"
    assert metadata["token_count"] == 20


def test_build_vector_index_writes_chroma_and_manifest(
    tmp_path: Path,
    chunks_jsonl: Path,
    sample_chunks: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vectorstore_dir = tmp_path / "vectorstore"
    embedder = BGEEmbedder(model_name="test-model")
    embedder._model = FakeModel()

    manifest = build_vector_index(
        chunks_path=chunks_jsonl,
        vectorstore_dir=vectorstore_dir,
        embedder=embedder,
    )

    assert manifest["bge_model_name"] == "test-model"
    assert manifest["chunk_count"] == len(sample_chunks)
    assert manifest["chunk_ids"] == [chunk["chunk_id"] for chunk in sample_chunks]

    manifest_path = vectorstore_dir / "index_manifest.json"
    assert manifest_path.is_file()
    on_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert on_disk["collection_name"] == COLLECTION_NAME
    assert on_disk["embedded_at"]

    import chromadb

    client = chromadb.PersistentClient(path=str(vectorstore_dir))
    collection = client.get_collection(COLLECTION_NAME)
    stored = collection.get(include=["metadatas", "documents"])
    assert set(stored["ids"]) == {chunk["chunk_id"] for chunk in sample_chunks}
    assert len(stored["documents"]) == len(sample_chunks)


@pytest.mark.skipif(
    not Path("data/chunks/chunks.jsonl").is_file(),
    reason="Corpus chunks not available",
)
def test_build_vector_index_integration(tmp_path: Path) -> None:
    """End-to-end index build with the real BGE model."""
    fixture = Path("data/chunks/chunks.jsonl")

    vectorstore_dir = tmp_path / "vectorstore"
    manifest = build_vector_index(
        chunks_path=fixture,
        vectorstore_dir=vectorstore_dir,
    )

    assert manifest["chunk_count"] >= 55
    assert manifest["bge_model_name"] == get_bge_model_name()
    assert (vectorstore_dir / "index_manifest.json").is_file()
