"""The database view the agent's tools get: SELECT statements only.

Tools receive an instance of this class and nothing else, so a tool cannot write to the database
whatever the model (or a document it read) asks for. The write side lives in repository.py.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

Row = dict[str, Any]

DOCUMENT_COLUMNS = (
    "id, filename, document_type, size_bytes, status, error_message, section_count, chunk_count,"
    " embedding_model, metadata, created_at, updated_at"
)


def to_vector_literal(values: Sequence[float]) -> str:
    """pgvector's text input format, e.g. '[0.1,0.2]'; passed as a bound parameter."""
    return "[" + ",".join(str(float(v)) for v in values) + "]"


def open_pool(database_url: str, timeout: float = 10) -> ConnectionPool:
    """Open a pool and wait for a first connection; raises PoolTimeout if unreachable."""
    pool = ConnectionPool(
        database_url,
        min_size=1,
        max_size=10,
        timeout=timeout,
        kwargs={"row_factory": dict_row, "connect_timeout": 5},
        open=False,
    )
    pool.open(wait=True, timeout=timeout)
    return pool


class ReadOnlyRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def ping(self) -> None:
        with self.pool.connection() as conn:
            conn.execute("SELECT 1")

    # ── Documents ────────────────────────────────────────────────────────────

    def list_documents(self) -> list[Row]:
        with self.pool.connection() as conn:
            return conn.execute(
                f"SELECT {DOCUMENT_COLUMNS} FROM documents ORDER BY created_at DESC"
            ).fetchall()

    def get_document(self, document_id: UUID) -> Row | None:
        with self.pool.connection() as conn:
            return conn.execute(
                f"SELECT {DOCUMENT_COLUMNS} FROM documents WHERE id = %s", (document_id,)
            ).fetchone()

    def find_documents_by_name(self, filename: str) -> list[Row]:
        with self.pool.connection() as conn:
            return conn.execute(
                f"SELECT {DOCUMENT_COLUMNS} FROM documents WHERE lower(filename) = lower(%s)"
                " ORDER BY created_at DESC",
                (filename,),
            ).fetchall()

    def has_searchable_documents(self, embedding_model: str) -> bool:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM documents WHERE status = 'ready'"
                " AND embedding_model = %s AND chunk_count > 0) AS found",
                (embedding_model,),
            ).fetchone()
        return bool(row["found"])

    # ── Sections (read_section) ──────────────────────────────────────────────

    def get_section(self, document_id: UUID, kind: str, number: int) -> Row | None:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT kind, number, locator, label, units FROM sections"
                " WHERE document_id = %s AND kind = %s AND number = %s",
                (document_id, kind, number),
            ).fetchone()

    def get_sections_in_range(
        self, document_id: UUID, kind: str, start: int, end: int
    ) -> list[Row]:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT kind, number, locator, label, units FROM sections"
                " WHERE document_id = %s AND kind = %s AND number BETWEEN %s AND %s"
                " ORDER BY number",
                (document_id, kind, start, end),
            ).fetchall()

    def number_range(self, document_id: UUID, kind: str) -> tuple[int, int] | None:
        """(lowest, highest) number stored for this kind, or None when the document has none."""
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT min(number) AS lo, max(number) AS hi FROM sections"
                " WHERE document_id = %s AND kind = %s",
                (document_id, kind),
            ).fetchone()
        if row is None or row["lo"] is None:
            return None
        return int(row["lo"]), int(row["hi"])

    def find_heading_sections(self, document_id: UUID, name: str) -> list[Row]:
        """Heading sections matching `name`: the full heading path, or the last heading in the
        path, case-insensitively. Falls back to a prefix match so a unique short name works."""
        exact = (
            "SELECT kind, number, locator, label, units FROM sections"
            " WHERE document_id = %(doc)s AND kind = 'section'"
            " AND (lower(substr(locator, 9)) = lower(%(name)s)"
            "      OR lower(substr(locator, 9)) LIKE '%% › ' || lower(%(name)s))"
            " ORDER BY ordinal"
        )
        prefix = (
            "SELECT kind, number, locator, label, units FROM sections"
            " WHERE document_id = %(doc)s AND kind = 'section'"
            " AND lower(substr(locator, 9)) LIKE lower(%(name)s) || '%%'"
            " ORDER BY ordinal LIMIT 11"
        )
        with self.pool.connection() as conn:
            rows = conn.execute(exact, {"doc": document_id, "name": name}).fetchall()
            if rows:
                return rows
            return conn.execute(prefix, {"doc": document_id, "name": name}).fetchall()

    # ── Search (search_knowledge_base) ───────────────────────────────────────
    # Only fully indexed documents embedded by the current model are ever searched:
    # vectors from different embedding models live in different spaces.

    def search_chunks(
        self,
        vector: Sequence[float],
        embedding_model: str,
        limit: int,
        document_id: UUID | None = None,
    ) -> list[Row]:
        """Exact cosine search (no ANN index): every chunk is scored, so recall is perfect."""
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT c.id AS chunk_id, c.document_id, d.filename AS document_name, c.content,"
                " c.units, c.unit_numbers, c.location, c.locator,"
                " 1 - (c.embedding <=> %(vector)s::vector) AS similarity"
                " FROM chunks c JOIN documents d ON d.id = c.document_id"
                " WHERE d.status = 'ready' AND d.embedding_model = %(model)s"
                " AND (%(document_id)s::uuid IS NULL OR c.document_id = %(document_id)s::uuid)"
                " ORDER BY c.embedding <=> %(vector)s::vector"
                " LIMIT %(limit)s",
                {
                    "vector": to_vector_literal(vector),
                    "model": embedding_model,
                    "document_id": document_id,
                    "limit": limit,
                },
            ).fetchall()
