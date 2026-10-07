"""FastAPI application: configuration, JSON logging, startup checks and error handlers.

Run with:  uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8010
"""

import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import anthropic
import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import ask, documents, health
from app.config import ConfigError, Settings, load_settings
from app.db.repository import Repository
from app.embeddings.provider import EmbeddingProvider, create_embedding_provider
from app.errors import AppError
from app.llm import create_llm_client

log = logging.getLogger("app")


class JsonFormatter(logging.Formatter):
    """One JSON object per line; `extra={...}` fields become top-level keys."""

    _RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
        "message",
        "color_message",  # uvicorn's ANSI-colored duplicate of `message`
    }

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry.update({k: v for k, v in vars(record).items() if k not in self._RESERVED})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    # One INFO line per outgoing HTTP call (Ollama via httpx, Anthropic SDK via httpx2) is noise.
    for name in ("httpx", "httpx2"):
        logging.getLogger(name).setLevel(logging.WARNING)


def error_response(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code)


def create_app(
    settings: Settings | None = None,
    *,
    embedder: EmbeddingProvider | None = None,
    llm: anthropic.Anthropic | None = None,
) -> FastAPI:
    """Build the app. Tests pass their own settings and fake embedding / Claude clients."""
    if settings is None:
        try:
            settings = load_settings()
        except ConfigError as exc:
            raise SystemExit(f"{exc}\nFix the values in .env and restart.") from None
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            repo = Repository.connect(settings.database_url.get_secret_value())
        except psycopg.OperationalError:
            log.error("PostgreSQL is unreachable. Start it with `docker compose up -d`.")
            raise
        # At most two documents process at once; later uploads wait in the queue.
        ingestion = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ingest")
        try:
            repo.init_schema(settings.embedding_dimension)
            interrupted = repo.fail_unfinished_documents()
            app.state.settings = settings
            app.state.repo = repo
            app.state.embedder = embedder or create_embedding_provider(settings)
            app.state.llm = llm or create_llm_client(settings)
            app.state.ingestion = ingestion
            log.info("startup complete", extra={"interrupted_documents": interrupted})
            yield
        finally:
            ingestion.shutdown(wait=False, cancel_futures=True)
            repo.close()

    app = FastAPI(title="Agentic RAG API", lifespan=lifespan)
    app.include_router(documents.router)
    app.include_router(ask.router)
    app.include_router(health.router)

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.code, exc.message, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first["loc"] if p != "body")
        message = f"{field}: {first['msg']}" if field else first["msg"]
        return error_response("INVALID_REQUEST", message, 422)

    @app.exception_handler(psycopg.OperationalError)
    async def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
        log.error("database unavailable", exc_info=exc)
        return error_response(
            "DATABASE_UNAVAILABLE", "The database is unavailable. Please try again shortly.", 503
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Starlette re-raises after this response, so uvicorn logs the traceback server-side.
        return error_response("INTERNAL_ERROR", "Something went wrong on our side.", 500)

    return app
