# Daily Ingestion Scheduler (GitHub Actions)

Phase 5 runs the offline Groww ingestion pipeline on a **daily schedule** via GitHub Actions. No long-running scheduler process is required on the API host.

## Schedule

| Setting | Value |
|---------|-------|
| **Local time** | **10:30 AM IST** (Asia/Kolkata) |
| **UTC cron** | `0 5 * * *` |
| **Workflow file** | [`.github/workflows/daily-ingestion.yml`](../.github/workflows/daily-ingestion.yml) |

GitHub scheduled workflows use UTC. IST is UTC+5:30, so 10:30 AM IST = 05:00 UTC.

## What runs

Each successful workflow execution:

1. Fetches all five Groww scheme pages
2. Parses and chunks content
3. Re-embeds chunks with BGE and rebuilds ChromaDB
4. Appends a line to `data/ingestion_log.jsonl`
5. Commits updated `data/chunks/`, `data/processed/`, `data/vectorstore/`, and the log (if changed)
6. Uploads key files as workflow artifacts

The entrypoint is:

```bash
python scripts/run_ingestion.py
```

Ingestion does **not** call Groq — no `GROQ_API_KEY` is required in the workflow.

## Manual run

1. Open the repository on GitHub
2. Go to **Actions** → **Daily Ingestion**
3. Click **Run workflow** → **Run workflow**

Or locally:

```bash
python scripts/run_ingestion.py
```

## GitHub secrets (optional)

| Secret | Purpose |
|--------|---------|
| `GITHUB_TOKEN` | Provided automatically; used to commit index updates |
| `REINDEX_API_URL` | `POST` URL to trigger `/api/reindex` on a deployed API |
| `REINDEX_API_SECRET` | Bearer token for the reindex hook |
| `DEPLOY_WEBHOOK_URL` | Hosting platform redeploy webhook after index commit |

## How the API gets fresh data

| Pattern | Description |
|---------|-------------|
| **Commit + redeploy** (MVP) | Push from the workflow triggers a hosting redeploy; API loads the new `data/vectorstore/` on start |
| **Reindex webhook** | Set `REINDEX_API_URL` to your deployed `POST /api/reindex` endpoint (requires `DEV_MODE=true` or a protected route) |
| **Artifacts only** | Download workflow artifacts in your deploy pipeline and mount into the container |

## Audit log

`data/ingestion_log.jsonl` — one JSON object per run:

```json
{
  "timestamp": "2026-07-05T05:00:12.345678+00:00",
  "status": "success",
  "chunk_count": 60,
  "duration_seconds": 142.5,
  "commit_sha": "abc123",
  "github_run_id": "12345678",
  "source": "github_actions",
  "counts": { "fetched": 5, "parsed": 5, "chunked": 60, "indexed": 60 }
}
```

Failed runs record `"status": "error"` and the workflow exits non-zero — **no index commit** occurs.

## Concurrency

The workflow uses `concurrency: group: daily-ingestion` so overlapping runs are queued rather than executed in parallel.
