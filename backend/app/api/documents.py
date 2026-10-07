"""Knowledge-base documents: upload, list, inspect, delete. The agent never reaches these."""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from starlette.datastructures import UploadFile

from app.errors import AppError
from app.ingestion.pipeline import ingest_document
from app.ingestion.validation import file_too_large, validate_upload

router = APIRouter(prefix="/api/documents", tags=["documents"])

MULTIPART_OVERHEAD_BYTES = 64 * 1024


class DocumentOut(BaseModel):
    id: UUID
    filename: str
    document_type: str
    size_bytes: int
    status: str
    error_message: str | None
    section_count: int
    chunk_count: int
    embedding_model: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@router.post("", status_code=202)
async def upload_document(request: Request) -> DocumentOut:
    """Validate and queue one file (form field `file`); processing continues in the background."""
    max_bytes = request.app.state.settings.max_upload_bytes
    declared = request.headers.get("content-length", "")
    # Reject oversized uploads before reading the body when the client declares the size.
    if declared.isdigit() and int(declared) > max_bytes + MULTIPART_OVERHEAD_BYTES:
        raise file_too_large(max_bytes)

    async with request.form(max_files=1, max_fields=1) as form:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise AppError("INVALID_REQUEST", "Attach the file in a form field named 'file'.")
        data = await upload.read(max_bytes + 1)
        filename = upload.filename

    return await run_in_threadpool(_accept_upload, request.app.state, filename, data)


def _accept_upload(state: Any, filename: str | None, data: bytes) -> dict[str, Any]:
    upload = validate_upload(filename, data, state.settings.max_upload_bytes)
    document = state.repo.create_document(
        filename=upload.filename,
        document_type=upload.document_type,
        size_bytes=len(upload.data),
        sha256=upload.sha256,
    )
    state.ingestion.submit(
        ingest_document,
        document["id"],
        upload.document_type,
        upload.data,
        repo=state.repo,
        embedder=state.embedder,
        settings=state.settings,
    )
    return document


@router.get("")
def list_documents(request: Request) -> list[DocumentOut]:
    return request.app.state.repo.list_documents()


@router.get("/{document_id}")
def get_document(document_id: UUID, request: Request) -> DocumentOut:
    document = request.app.state.repo.get_document(document_id)
    if document is None:
        raise AppError("NOT_FOUND", "Document not found.", 404)
    return document


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: UUID, request: Request) -> Response:
    if not request.app.state.repo.delete_document(document_id):
        raise AppError("NOT_FOUND", "Document not found.", 404)
    return Response(status_code=204)
