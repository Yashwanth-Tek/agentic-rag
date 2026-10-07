"""Turns validated file bytes into sections.

Every section carries only location facts the parser actually knows (page, heading path, row,
record, part); nothing is guessed. Document-level facts (page count, columns, outline) are
returned as metadata and shown to the agent by list_documents.
"""

import csv
import io
import json
import logging
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from docx import Document
from docx.table import Table
from pypdf import PdfReader
from pypdf.errors import DependencyError

from app.errors import AppError
from app.ingestion.sections import (
    HeadingSectionBuilder,
    Section,
    normalize_text,
    page_section,
    part_sections,
    record_section,
    row_section,
)

log = logging.getLogger(__name__)

MAX_OUTLINE_ENTRIES = 200


@dataclass(frozen=True)
class Extraction:
    sections: list[Section]
    metadata: dict[str, Any] = field(default_factory=dict)


def extract(document_type: str, data: bytes, *, part_chars: int) -> Extraction:
    try:
        extraction = _EXTRACTORS[document_type](data, part_chars)
    except AppError:
        raise
    except Exception as exc:
        log.warning(
            "extraction failed", extra={"document_type": document_type, "error": repr(exc)[:300]}
        )
        raise AppError(
            "CORRUPTED_FILE", "This file couldn't be read. It may be corrupted or incomplete."
        ) from exc

    if not extraction.sections:
        message = "This file contains no readable text."
        if document_type == "pdf":
            message = "This PDF has no extractable text. Scanned (image) PDFs aren't supported."
        raise AppError("NO_TEXT", message)
    characters = sum(len(unit) for section in extraction.sections for unit in section.units)
    return Extraction(extraction.sections, {**extraction.metadata, "characters": characters})


def _decode(data: bytes) -> str:
    return data.decode("utf-8-sig")  # validation already confirmed UTF-8


def _extract_pdf(data: bytes, part_chars: int) -> Extraction:
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            unlocked = bool(reader.decrypt(""))
        except DependencyError:
            unlocked = False
        if not unlocked:
            raise AppError(
                "ENCRYPTED_FILE",
                "This PDF is password-protected. Remove the protection and upload it again.",
            )
    sections = []
    for number, page in enumerate(reader.pages, start=1):
        section = page_section(number, page.extract_text() or "")
        if section:
            sections.append(section)
    return Extraction(sections, {"pages": len(reader.pages)})


_HEADING_STYLE = re.compile(r"Heading ([1-9])")


def _extract_docx(data: bytes, part_chars: int) -> Extraction:
    """One section per heading, labelled with its heading path; tables stay in document order."""
    document = Document(io.BytesIO(data))
    builder = HeadingSectionBuilder(part_chars)
    for block in document.iter_inner_content():
        if isinstance(block, Table):
            for row in block.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                builder.add_line(" | ".join(cells))
            builder.add_line("")
            continue
        text = block.text.strip()
        style = block.style.name if block.style is not None else ""
        match = _HEADING_STYLE.fullmatch(style)
        level = int(match.group(1)) if match else (1 if style == "Title" else 0)
        if level and text:
            builder.start_heading(level, text)
        else:
            builder.add_line(text)
            builder.add_line("")  # each Word paragraph is its own citable unit
    return Extraction(builder.finish(), _outline_metadata(builder))


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_MD_FENCE = re.compile(r"^\s*(```|~~~)")


def _extract_markdown(data: bytes, part_chars: int) -> Extraction:
    builder = HeadingSectionBuilder(part_chars)
    in_code_block = False
    for line in _decode(data).splitlines():
        if _MD_FENCE.match(line):
            in_code_block = not in_code_block
        match = None if in_code_block else _MD_HEADING.match(line)
        if match:
            builder.start_heading(len(match.group(1)), match.group(2))
        else:
            builder.add_line(line)
    return Extraction(builder.finish(), _outline_metadata(builder))


def _outline_metadata(builder: HeadingSectionBuilder) -> dict[str, Any]:
    if not builder.outline:
        return {}
    return {
        "sections": len(builder.outline),
        "outline": builder.outline[:MAX_OUTLINE_ENTRIES],
    }


def _extract_text(data: bytes, part_chars: int) -> Extraction:
    sections = part_sections(_decode(data), part_chars)
    return Extraction(sections, {"parts": len(sections)})


def _extract_csv(data: bytes, part_chars: int) -> Extraction:
    """One section per row, written as `Column: value` pairs so every unit is self-describing."""
    text = _decode(data)
    try:
        dialect: type[csv.Dialect] = csv.Sniffer().sniff(text[:10_000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader, [])
    columns = [name.strip() or f"Column {i}" for i, name in enumerate(header, start=1)]
    sections = []
    # Row numbers match a spreadsheet: the header is row 1, the first record is row 2.
    for row_number, row in enumerate(reader, start=2):
        pairs = [
            f"{columns[i] if i < len(columns) else f'Column {i + 1}'}: {value.strip()}"
            for i, value in enumerate(row)
            if value.strip()
        ]
        if pairs:
            sections.append(row_section(row_number, " | ".join(pairs)))
    metadata: dict[str, Any] = {"rows": len(sections), "columns": columns}
    if sections:
        metadata["row_range"] = f"{sections[0].number}-{sections[-1].number}"
    return Extraction(sections, metadata)


def _extract_json(data: bytes, part_chars: int) -> Extraction:
    """Flatten to `path: value` lines; a top-level array becomes one section per record."""
    try:
        value = json.loads(_decode(data))
    except json.JSONDecodeError as exc:
        raise AppError(
            "CORRUPTED_FILE", f"This isn't valid JSON (line {exc.lineno}, column {exc.colno})."
        ) from exc
    if isinstance(value, list):
        sections = [
            record_section(number, "\n".join(_flatten_json(item, "")))
            for number, item in enumerate(value, start=1)
            if normalize_text("\n".join(_flatten_json(item, "")))
        ]
        return Extraction(sections, {"records": len(value)})
    sections = part_sections("\n\n".join(_flatten_json(value, "")), part_chars)
    return Extraction(sections, {"parts": len(sections)})


def _flatten_json(value: object, path: str) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _flatten_json(child, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _flatten_json(child, f"{path}[{index}]")
    else:
        rendered = value if isinstance(value, str) else json.dumps(value)
        yield f"{path}: {rendered}" if path else str(rendered)


_EXTRACTORS: dict[str, Callable[[bytes, int], Extraction]] = {
    "pdf": _extract_pdf,
    "docx": _extract_docx,
    "md": _extract_markdown,
    "txt": _extract_text,
    "csv": _extract_csv,
    "json": _extract_json,
}
