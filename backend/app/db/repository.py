"""The write side of the database: schema, document lifecycle, indexing.

Each method runs in its own short transaction: psycopg commits when the `with pool.connection()`
block exits normally and rolls back on an exception. The agent's tools never see this class.
"""

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from app.config import ConfigError
from app.db.read_repository import DOCUMENT_COLUMNS, ReadOnlyRepository, Row, to_vector_literal
from app.errors import AppError
from app.ingestion.chunking import Chunk
from app.ingestion.sections import Section

SCHEMA_FILE = Path(__file__).with_name("schema.sql")
IN_PROGRESS = ("uploaded", "extracting", "embedding", "indexing")


class Repository(ReadOnlyRepository):
    @classmethod
    def connect(cls, database_url: str, timeout: float = 10) -> "Repository":
        from app.db.read_repository import open_pool

        return cls(open_pool(database_url, timeout))

    def close(self) -> None:
        self.pool.close()

    def read_only(self) -> ReadOnlyRepository:
        """The SELECT-only view handed to the agent's tools."""
        return ReadOnlyRepository(self.pool)

    def init_schema(self, embedding_dimension: int) -> None:
        """Create missing tables; refuse to run if the stored vector size differs from config."""
        ddl = SCHEMA_FILE.read_text(encoding="utf-8").replace(
            "{{EMBEDDING_DIMENSION}}", str(int(embedding_dimension))
        )
        with self.pool.connection() as conn:
            conn.execute(ddl)
            row = conn.execute(
                "SELECT format_type(atttypid, atttypmod) AS column_type FROM pg_attribute"
                " WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
            ).fetchone()
        expected = f"vector({embedding_dimension})"
        if row is None or row["column_type"] != expected:
            found = row["column_type"] if row else "missing"
            raise ConfigError(
                f"EMBEDDING_DIMENSION is {embedding_dimension} but the database stores {found}. "
                "Changing the dimension means re-indexing every document: drop the tables (or the "
                "database volume) and upload the documents again."
            )

    # ── Documents ────────────────────────────────────────────────────────────

    def create_document(
        self, *, filename: str, document_type: str, size_bytes: int, sha256: str
    ) -> Row:
        """Insert a queued document. Re-uploading content that previously failed replaces the
        failed record; any other duplicate content is rejected."""
        with self.pool.connection() as conn:
            existing = conn.execute(
                "SELECT id, filename, status FROM documents WHERE content_sha256 = %s FOR UPDATE",
                (sha256,),
            ).fetchone()
            if existing and existing["status"] != "failed":
                raise _duplicate(existing["filename"])
            if existing:
                conn.execute("DELETE FROM documents WHERE id = %s", (existing["id"],))
            try:
                return conn.execute(
                    "INSERT INTO documents (filename, document_type, size_bytes, content_sha256,"
                    " status) VALUES (%s, %s, %s, %s, 'uploaded')"
                    f" RETURNING {DOCUMENT_COLUMNS}",
                    (filename, document_type, size_bytes, sha256),
                ).fetchone()
            except UniqueViolation:  # the same file uploaded twice at the same moment
                raise _duplicate(filename) from None

    def delete_document(self, document_id: UUID) -> bool:
        with self.pool.connection() as conn:
            deleted = conn.execute("DELETE FROM documents WHERE id = %s", (document_id,)).rowcount
        return deleted > 0

    def set_status(self, document_id: UUID, status: str) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "UPDATE documents SET status = %s, updated_at = now() WHERE id = %s",
                (status, document_id),
            )

    def mark_failed(self, document_id: UUID, message: str) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "UPDATE documents SET status = 'failed', error_message = %s, updated_at = now()"
                " WHERE id = %s",
                (message, document_id),
            )

    def fail_unfinished_documents(self) -> int:
        """At startup, documents still in progress were interrupted by a restart."""
        with self.pool.connection() as conn:
            return conn.execute(
                "UPDATE documents SET status = 'failed', updated_at = now(),"
                " error_message = 'Processing was interrupted by a server restart."
                " Please upload the file again.'"
                " WHERE status = ANY(%s)",
                (list(IN_PROGRESS),),
            ).rowcount

    def save_extraction(
        self,
        document_id: UUID,
        sections: Sequence[Section],
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
        embedding_model: str,
        metadata: dict,
    ) -> bool:
        """Store sections and chunks and mark the document ready in one transaction, so a
        document is never searchable half-indexed. Returns False if it was deleted meanwhile."""
        with self.pool.connection() as conn:
            updated = conn.execute(
                "UPDATE documents SET status = 'ready', section_count = %s, chunk_count = %s,"
                " embedding_model = %s, metadata = %s, error_message = NULL, updated_at = now()"
                " WHERE id = %s RETURNING id",
                (len(sections), len(chunks), embedding_model, Jsonb(metadata), document_id),
            ).fetchone()
            if updated is None:
                return False
            with conn.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO sections (document_id, ordinal, kind, number, locator, label,"
                    " units) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    [
                        (
                            document_id,
                            ordinal,
                            section.kind,
                            section.number,
                            section.locator,
                            section.label,
                            Jsonb(section.units),
                        )
                        for ordinal, section in enumerate(sections)
                    ],
                )
                cursor.executemany(
                    "INSERT INTO chunks (document_id, chunk_index, content, units, unit_numbers,"
                    " locator, location, embedding)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)",
                    [
                        (
                            document_id,
                            index,
                            chunk.content,
                            Jsonb(chunk.units),
                            Jsonb(chunk.unit_numbers) if chunk.unit_numbers else None,
                            chunk.locator,
                            Jsonb(chunk.location),
                            to_vector_literal(vector),
                        )
                        for index, (chunk, vector) in enumerate(
                            zip(chunks, embeddings, strict=True)
                        )
                    ],
                )
        return True


def _duplicate(filename: str) -> AppError:
    return AppError(
        "DUPLICATE_DOCUMENT",
        f'This content is already in the knowledge base as "{filename}".',
        409,
    )
