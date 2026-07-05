"""Unit tests for scripts/build_index.py orchestration (Phase 1.6)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts import build_index


def test_run_ingestion_pipeline_full(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(build_index, "run_fetch", lambda **_: calls.append("fetch") or 5)
    monkeypatch.setattr(build_index, "run_parse", lambda **_: calls.append("parse") or 5)
    monkeypatch.setattr(build_index, "run_chunk", lambda **_: calls.append("chunk") or 60)

    counts = build_index.run_ingestion_pipeline()

    assert calls == ["fetch", "parse", "chunk"]
    assert counts == {"fetched": 5, "parsed": 5, "chunked": 60}


def test_run_ingestion_pipeline_chunk_only_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        build_index,
        "run_chunk",
        lambda **_: 60,
    )
    monkeypatch.setattr(
        build_index,
        "run_fetch",
        MagicMock(side_effect=AssertionError("fetch should not run")),
    )
    monkeypatch.setattr(
        build_index,
        "run_parse",
        MagicMock(side_effect=AssertionError("parse should not run")),
    )

    counts = build_index.run_ingestion_pipeline(fetch=False, parse=False, chunk=True)
    assert counts == {"chunked": 60}


def test_main_fetch_only(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"fetch": False}

    def fake_fetch(**_: object) -> int:
        called["fetch"] = True
        return 5

    monkeypatch.setattr(build_index, "run_fetch", fake_fetch)
    monkeypatch.setattr(
        build_index,
        "run_ingestion_pipeline",
        MagicMock(side_effect=AssertionError("pipeline should not run")),
    )

    assert build_index.main(["--fetch-only"]) == 0
    assert called["fetch"] is True


def test_main_chunk_only(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"chunk": False}

    def fake_chunk(**_: object) -> int:
        called["chunk"] = True
        return 60

    monkeypatch.setattr(build_index, "run_chunk", fake_chunk)
    monkeypatch.setattr(
        build_index,
        "run_fetch",
        MagicMock(side_effect=AssertionError("fetch should not run")),
    )

    assert build_index.main(["--chunk-only"]) == 0
    assert called["chunk"] is True


def test_main_rejects_conflicting_flags() -> None:
    with pytest.raises(SystemExit):
        build_index.main(["--fetch-only", "--chunk-only"])


def test_main_index_only(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"index": False}

    def fake_index(**_: object) -> int:
        called["index"] = True
        return 60

    monkeypatch.setattr(build_index, "run_index", fake_index)
    monkeypatch.setattr(
        build_index,
        "run_ingestion_pipeline",
        MagicMock(side_effect=AssertionError("pipeline should not run")),
    )

    assert build_index.main(["--index"]) == 0
    assert called["index"] is True


def test_chunk_only_integration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    chunks_path = tmp_path / "chunks.jsonl"

    fixture = Path("data/processed/hdfc-mid-cap-fund-direct-growth.json")
    if not fixture.is_file():
        pytest.skip("Processed fixture not available")

    (processed_dir / fixture.name).write_text(
        fixture.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    monkeypatch.setattr(build_index, "DEFAULT_PROCESSED_DIR", processed_dir)
    monkeypatch.setattr(build_index, "DEFAULT_CHUNKS_PATH", chunks_path)

    assert build_index.main(["--chunk-only", "--processed-dir", str(processed_dir), "--chunks-path", str(chunks_path)]) == 0
    assert chunks_path.is_file()
    assert sum(1 for _ in chunks_path.open(encoding="utf-8")) == 12
