-- Applied at startup; every statement is idempotent.
-- {{EMBEDDING_DIMENSION}} is replaced with the validated EMBEDDING_DIMENSION setting.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    filename        text NOT NULL,
    document_type   text NOT NULL,
    size_bytes      bigint NOT NULL,
    content_sha256  text NOT NULL UNIQUE,
    status          text NOT NULL CHECK (status IN
                    ('uploaded', 'extracting', 'embedding', 'indexing', 'ready', 'failed')),
    error_message   text,
    section_count   integer NOT NULL DEFAULT 0,
    chunk_count     integer NOT NULL DEFAULT 0,
    embedding_model text,
    metadata        jsonb NOT NULL DEFAULT '{}',
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Locator-addressable extracted units: what read_section returns and what chunks are cut from.
CREATE TABLE IF NOT EXISTS sections (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    ordinal     integer NOT NULL,                       -- document order
    kind        text NOT NULL CHECK (kind IN ('page', 'section', 'row', 'record', 'part')),
    number      integer,                                -- page / row / record / part number
    locator     text NOT NULL,                          -- "page:4" | "section:A › B" | "row:13" | …
    label       text NOT NULL,                          -- "Page 4" | "Section: A › B" | "Row 13" | …
    units       jsonb NOT NULL,                         -- citable units (paragraphs, or one row/record)
    UNIQUE (document_id, ordinal),
    UNIQUE (document_id, locator)
);

CREATE INDEX IF NOT EXISTS sections_by_number ON sections (document_id, kind, number);

-- The search index. Each chunk keeps the citable units it was built from.
CREATE TABLE IF NOT EXISTS chunks (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    chunk_index  integer NOT NULL,
    content      text NOT NULL,
    units        jsonb NOT NULL,
    unit_numbers jsonb,                                 -- row/record number per unit; NULL for prose
    locator      text NOT NULL,                         -- read_section location of this chunk
    location     jsonb NOT NULL DEFAULT '{}',           -- {"page": 4} | {"rows": "12–18"} | {"section": "…"}
    embedding    vector({{EMBEDDING_DIMENSION}}) NOT NULL,
    UNIQUE (document_id, chunk_index)
);
