"""CI entrypoint for daily Groww corpus ingestion (Phase 5).

Runs fetch → parse → chunk → embed/index, appends an audit line to
``data/ingestion_log.jsonl``, and exits non-zero on failure so GitHub Actions
does not commit a partial index.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ingestion.fetcher import FetchError
from scripts.build_index import run_index, run_ingestion_pipeline

logger = logging.getLogger(__name__)

INGESTION_LOG_PATH = PROJECT_ROOT / "data" / "ingestion_log.jsonl"


def append_ingestion_log(entry: dict[str, Any]) -> None:
    """Append one JSON line to the ingestion audit log."""
    INGESTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with INGESTION_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def run_daily_ingestion() -> dict[str, int]:
    """Execute the full offline ingestion pipeline including vector indexing."""
    counts = run_ingestion_pipeline(fetch=True, parse=True, chunk=True)
    counts["indexed"] = run_index()
    return counts


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    started_at = time.perf_counter()
    commit_sha = os.getenv("GITHUB_SHA", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    source = "github_actions" if run_id else "manual"

    try:
        counts = run_daily_ingestion()
        duration_seconds = round(time.perf_counter() - started_at, 2)
        chunk_count = counts.get("indexed", counts.get("chunked", 0))

        append_ingestion_log(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "success",
                "chunk_count": chunk_count,
                "duration_seconds": duration_seconds,
                "commit_sha": commit_sha,
                "github_run_id": run_id,
                "source": source,
                "counts": counts,
            }
        )

        logger.info(
            "Ingestion complete in %.1fs — fetched=%s parsed=%s chunked=%s indexed=%s",
            duration_seconds,
            counts.get("fetched"),
            counts.get("parsed"),
            counts.get("chunked"),
            counts.get("indexed"),
        )
        return 0
    except (FetchError, FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        duration_seconds = round(time.perf_counter() - started_at, 2)
        append_ingestion_log(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "error",
                "error": str(exc),
                "duration_seconds": duration_seconds,
                "commit_sha": commit_sha,
                "github_run_id": run_id,
                "source": source,
            }
        )
        logger.error("Ingestion failed after %.1fs: %s", duration_seconds, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
