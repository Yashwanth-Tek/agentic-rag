"""Runs one document through extract → chunk → embed → index, recording each stage as its status.

Runs on a background worker thread, so every failure is caught and stored on the document.
"""

import logging
import time
from uuid import UUID

from app.config import Settings
from app.db.repository import Repository
from app.embeddings.provider import EmbeddingProvider
from app.errors import AppError
from app.ingestion.chunking import chunk_sections
from app.ingestion.extractors import extract

log = logging.getLogger(__name__)

UNEXPECTED_FAILURE = "Processing failed unexpectedly. Please try uploading the file again."


def ingest_document(
    document_id: UUID,
    document_type: str,
    data: bytes,
    *,
    repo: Repository,
    embedder: EmbeddingProvider,
    settings: Settings,
) -> None:
    started = time.perf_counter()
    context = {"document_id": str(document_id), "document_type": document_type}
    try:
        repo.set_status(document_id, "extracting")
        extraction = extract(document_type, data, part_chars=settings.text_part_chars)
        chunks = chunk_sections(
            extraction.sections, settings.chunk_size_chars, settings.chunk_overlap_chars
        )

        repo.set_status(document_id, "embedding")
        embeddings = embedder.embed_documents([chunk.content for chunk in chunks])

        repo.set_status(document_id, "indexing")
        stored = repo.save_extraction(
            document_id,
            extraction.sections,
            chunks,
            embeddings,
            embedder.model_id,
            extraction.metadata,
        )
    except AppError as exc:
        log.warning("document failed", extra={**context, "code": exc.code})
        _record_failure(repo, document_id, exc.message)
        return
    except Exception:
        log.exception("document failed unexpectedly", extra=context)
        _record_failure(repo, document_id, UNEXPECTED_FAILURE)
        return

    elapsed_ms = round((time.perf_counter() - started) * 1000)
    if stored:
        log.info(
            "document ready",
            extra={
                **context,
                "sections": len(extraction.sections),
                "chunks": len(chunks),
                "ms": elapsed_ms,
            },
        )
    else:
        log.info("document deleted while processing", extra=context)


def _record_failure(repo: Repository, document_id: UUID, message: str) -> None:
    try:
        repo.mark_failed(document_id, message)
    except Exception:
        log.exception("could not record document failure", extra={"document_id": str(document_id)})
