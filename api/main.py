"""FastAPI app factory with CORS and route registration."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.chat import router as chat_router
from ingestion.indexer import DEFAULT_VECTORSTORE_DIR
from rag.retriever import IndexNotReadyError, load_index_manifest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _validate_startup_config() -> None:
    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError("GROQ_API_KEY is not set. Copy .env.example to .env and add your key.")
    load_index_manifest(DEFAULT_VECTORSTORE_DIR)


def create_app() -> FastAPI:
    app = FastAPI(
        title="HDFC Mutual Fund FAQ Assistant",
        description="Facts-only RAG chatbot for five HDFC schemes on Groww.",
        version="0.1.0",
    )

    cors_origins = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:5500",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in cors_origins.split(",") if origin.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def on_startup() -> None:
        _validate_startup_config()

    app.include_router(chat_router)
    return app


app = create_app()
