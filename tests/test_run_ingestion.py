"""Unit tests for scripts/run_ingestion.py (Phase 5)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts import run_ingestion


def test_run_daily_ingestion_calls_full_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline_mock = MagicMock(return_value={"fetched": 5, "parsed": 5, "chunked": 60})
    index_mock = MagicMock(return_value=60)
    monkeypatch.setattr(run_ingestion, "run_ingestion_pipeline", pipeline_mock)
    monkeypatch.setattr(run_ingestion, "run_index", index_mock)

    counts = run_ingestion.run_daily_ingestion()

    pipeline_mock.assert_called_once_with(fetch=True, parse=True, chunk=True)
    index_mock.assert_called_once_with()
    assert counts == {"fetched": 5, "parsed": 5, "chunked": 60, "indexed": 60}


def test_main_success_writes_audit_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "ingestion_log.jsonl"
    monkeypatch.setattr(run_ingestion, "INGESTION_LOG_PATH", log_path)
    monkeypatch.setattr(
        run_ingestion,
        "run_daily_ingestion",
        lambda: {"fetched": 5, "parsed": 5, "chunked": 60, "indexed": 60},
    )
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setenv("GITHUB_RUN_ID", "99")

    assert run_ingestion.main() == 0

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["status"] == "success"
    assert entry["chunk_count"] == 60
    assert entry["commit_sha"] == "abc123"
    assert entry["github_run_id"] == "99"
    assert entry["source"] == "github_actions"
    assert entry["counts"]["indexed"] == 60


def test_main_failure_exits_nonzero_and_logs_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "ingestion_log.jsonl"
    monkeypatch.setattr(run_ingestion, "INGESTION_LOG_PATH", log_path)

    def fail() -> dict[str, int]:
        raise run_ingestion.FetchError("Groww fetch failed", ["https://groww.in/example"])

    monkeypatch.setattr(run_ingestion, "run_daily_ingestion", fail)

    assert run_ingestion.main() == 1

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["status"] == "error"
    assert "Groww fetch failed" in entry["error"]
