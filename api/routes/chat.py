"""Chat, schemes, and reindex API routes."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api.rate_limit import RateLimitExceededError, get_chat_rate_limiter
from ingestion.fetcher import load_sources
from rag.pipeline import get_pipeline, process_message
from rag.retriever import IndexNotReadyError
from scripts.build_index import run_index

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class SchemeResponse(BaseModel):
    name: str
    category: str
    url: str
    aliases: list[str]


class SchemesResponse(BaseModel):
    schemes: list[SchemeResponse]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/schemes", response_model=SchemesResponse)
def list_schemes() -> SchemesResponse:
    schemes = [
        SchemeResponse(
            name=scheme.name,
            category=scheme.category,
            url=scheme.url,
            aliases=list(scheme.aliases),
        )
        for scheme in load_sources()
    ]
    return SchemesResponse(schemes=schemes)


@router.post("/chat")
def chat(request_body: ChatRequest, request: Request) -> dict:
    client_host = request.client.host if request.client else "unknown"
    try:
        get_chat_rate_limiter().check(client_host)
    except RateLimitExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    try:
        return process_message(request_body.message.strip())
    except IndexNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/reindex")
def reindex() -> dict[str, str | int]:
    if os.getenv("DEV_MODE", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="Reindex is disabled. Set DEV_MODE=true.")
    try:
        count = run_index()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    get_pipeline().retriever.reset_collection()
    return {"status": "ok", "chunk_count": count}
