"""The three read-only tools Claude can call, bound to one AgentRun.

Each wrapper does, in order: validate inputs → check the run's limits → emit `running` →
execute (SELECT statements and, for search, one embedding call) → record evidence → emit `done`.
Problems are raised as ToolError, which the SDK runner turns into an error tool result so Claude
can adapt; a service outage is also stored as `run.fatal` so the loop stops.
"""

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg
from anthropic import beta_tool
from anthropic.lib.tools import ToolError

from app.agent.run import AgentRun, EvidenceItem, location_label, safe_detail
from app.config import Settings
from app.db.read_repository import ReadOnlyRepository, Row
from app.embeddings.provider import EmbeddingProvider
from app.errors import AppError

MAX_QUERY_CHARS = 500
MAX_OUTLINE_IN_LISTING = 30

LIMIT_MESSAGE = (
    "Retrieval limit reached: no more tool calls are allowed for this question. Answer using "
    "only the passages already retrieved, or say that the knowledge base does not contain enough "
    "information."
)
TIME_MESSAGE = (
    "Time limit reached: no more tool calls are allowed for this question. Answer using only the "
    "passages already retrieved, or say that the knowledge base does not contain enough "
    "information."
)
LOCATION_HELP = (
    "Locations for read_section: page:N · section:<heading or heading path> · rows:A-B · "
    "records:A-B · part:N"
)
DATABASE_DOWN = AppError(
    "DATABASE_UNAVAILABLE", "The database is unavailable. Please try again shortly.", 503
)

_LOCATION = re.compile(r"^\s*(page|part|section|rows?|records?)\s*:\s*(.+?)\s*$", re.IGNORECASE)
_RANGE = re.compile(r"^(\d+)\s*(?:-|–|to)\s*(\d+)$|^(\d+)$")


def make_tools(
    run: AgentRun, repo: ReadOnlyRepository, embedder: EmbeddingProvider, settings: Settings
) -> list:
    """Three @beta_tool functions whose closures hold this run's state."""

    def search_knowledge_base(query: str, document: str | None = None) -> list[dict[str, Any]]:
        """Search the knowledge base for passages relevant to a query.

        Call this to find where information is. Use a specific, focused query (a topic, a name,
        a metric, a date) and call it again with different wording, once per part of a
        multi-part question, or per document when comparing documents. Each result shows the
        document and location it came from and can be cited.

        Args:
            query: What to look for, in a few words or one short sentence (max 500 characters).
            document: Optional document id or exact file name to search within one document.
        """
        query = (query or "").strip()
        if not query:
            raise ToolError("query must not be empty.")
        if len(query) > MAX_QUERY_CHARS:
            raise ToolError(
                f"query is too long ({len(query)} characters; the maximum is {MAX_QUERY_CHARS})."
            )
        _guard(run)
        doc = _resolve_document(run, repo, document) if document else None
        detail = query if doc is None else f"{query} · in {doc['filename']}"
        activity = run.activity_start("search", "Searching knowledge base", detail)
        try:
            vector = embedder.embed_query(query)
            with _database(run, activity):
                rows = repo.search_chunks(
                    vector,
                    embedder.model_id,
                    settings.search_top_k,
                    document_id=doc["id"] if doc else None,
                )
        except AppError as exc:
            run.activity_failed(activity, exc.message)
            raise ToolError(f"Search is unavailable right now: {exc.message}") from exc
        hits = [row for row in rows if row["similarity"] >= settings.search_min_similarity]
        if not hits:
            run.activity_done(activity, results=0)
            return [
                _text(
                    f'No passages scored above the relevance threshold for "{query}". Try '
                    "different wording, a narrower topic, or list_documents() to see what exists."
                )
            ]
        items = [
            run.record(
                source=f"kb://{row['document_id']}/{row['locator']}?chunk={row['chunk_id']}",
                document_id=row["document_id"],
                document_name=row["document_name"],
                locator=row["locator"],
                location=row["location"],
                units=row["units"],
                unit_numbers=row["unit_numbers"],
                origin="search",
            )
            for row in hits
        ]
        run.activity_done(activity, results=len(hits))
        # The API requires a tool result to hold search_result blocks only (no mixed text), so
        # the relevance score travels in each block's title.
        return [
            _search_result(item, suffix=f" · relevance {row['similarity']:.2f}")
            for item, row in zip(items, hits, strict=True)
        ]

    def list_documents() -> str:
        """List the documents in the knowledge base with their status and structure.

        Call this when you are unsure what the knowledge base contains, when the question names
        a document, or when you need a document's structure (pages, sections and their headings,
        rows and columns, records) before reading it with read_section.
        """
        _guard(run)
        activity = run.activity_start("list", "Listing documents")
        with _database(run, activity):
            rows = repo.list_documents()
        entries = [_document_entry(row, embedder.model_id) for row in rows]
        order = {"ready": 0, "processing": 1, "failed": 2}
        entries.sort(key=lambda entry: (order[entry["status"]], entry["name"].lower()))
        run.activity_done(activity, results=len(entries))
        return json.dumps(entries, ensure_ascii=False) + "\n" + LOCATION_HELP

    def read_section(document: str, location: str) -> list[dict[str, Any]]:
        """Read one exact part of a document: a page, a heading section, rows, records or a part.

        Call this to read a table's rows, a named section, the page around a search hit, or a
        part of an unstructured text. The content comes back with its exact location and can
        be cited.

        Args:
            document: The document id or exact file name (see list_documents).
            location: One of: page:N · section:<heading or heading path> · rows:A-B ·
                records:A-B · part:N. Examples: "page:4", "section:Severity levels",
                "rows:12-18", "records:3-5", "part:2".
        """
        _guard(run)
        activity = run.activity_start(
            "read", "Reading document", f"{document or '?'} · {location or '?'}"
        )
        try:
            doc = _resolve_document(run, repo, document)
            item, note = _read(run, repo, settings, doc, location)
        except ToolError as exc:
            run.activity_failed(activity, str(exc))
            raise
        run.activity_done(activity, detail=safe_detail(f"{item.document_name} · {item.label}"))
        # A truncation note cannot be a separate text block (see search), so it joins the title.
        return [_search_result(item, suffix=f" {note}" if note else "")]

    return [beta_tool(search_knowledge_base), beta_tool(list_documents), beta_tool(read_section)]


# ── Shared helpers ───────────────────────────────────────────────────────────


def _guard(run: AgentRun) -> None:
    """Enforce the run's limits before any tool does work; every executed call counts."""
    if run.cancelled:
        raise ToolError("The request was cancelled.")
    if run.fatal is not None:
        raise ToolError("A service is unavailable. Stop and answer from what you already have.")
    if run.over_deadline():
        run.stop("time")
        raise ToolError(TIME_MESSAGE)
    if not run.budget_left():
        run.stop("tool_calls")
        raise ToolError(LIMIT_MESSAGE)
    run.tool_calls += 1


@contextmanager
def _database(run: AgentRun, activity: int | None = None) -> Iterator[None]:
    """Turn a lost database into a fatal run error (the loop stops) and a tool error."""
    try:
        yield
    except psycopg.OperationalError as exc:
        run.fatal = DATABASE_DOWN
        if activity is not None:
            run.activity_failed(activity, DATABASE_DOWN.message)
        raise ToolError("The database is unavailable.") from exc


def _resolve_document(run: AgentRun, repo: ReadOnlyRepository, reference: str | None) -> Row:
    reference = (reference or "").strip()
    if not reference:
        raise ToolError("document must be a document id or file name.")
    with _database(run):
        try:
            document_id = UUID(reference)
        except ValueError:
            matches = repo.find_documents_by_name(reference)
        else:
            found = repo.get_document(document_id)
            matches = [found] if found else []
    if not matches:
        raise ToolError(
            f'No document "{reference}" in the knowledge base. Call list_documents() to see '
            "the available documents and their ids."
        )
    if len(matches) > 1:
        raise ToolError(
            f'Several documents are named "{reference}". Use the document id from '
            "list_documents() instead."
        )
    doc = matches[0]
    if doc["status"] != "ready":
        state = "failed to process" if doc["status"] == "failed" else "still being processed"
        raise ToolError(f'"{doc["filename"]}" {state} and cannot be read.')
    return doc


def _document_entry(row: Row, current_model: str) -> dict[str, Any]:
    """Safe, selection-relevant facts about a document; never paths, hashes or settings."""
    status = row["status"] if row["status"] in ("ready", "failed") else "processing"
    entry: dict[str, Any] = {
        "id": str(row["id"]),
        "name": row["filename"],
        "type": row["document_type"],
        "status": status,
        "searchable": status == "ready" and row["embedding_model"] == current_model,
    }
    metadata = row["metadata"] or {}
    for key in ("pages", "rows", "row_range", "records", "sections", "parts"):
        if key in metadata:
            entry[key] = metadata[key]
    if "columns" in metadata:
        entry["columns"] = metadata["columns"]
    if "outline" in metadata:
        outline = metadata["outline"]
        entry["outline"] = outline[:MAX_OUTLINE_IN_LISTING]
        if len(outline) > MAX_OUTLINE_IN_LISTING:
            entry["outline_truncated"] = True
    return entry


def _read(
    run: AgentRun, repo: ReadOnlyRepository, settings: Settings, doc: Row, location: str
) -> tuple[EvidenceItem, str | None]:
    match = _LOCATION.match(location or "")
    if not match:
        raise ToolError(f'Invalid location "{location}". {LOCATION_HELP}')
    kind, value = match.group(1).lower(), match.group(2)
    name = doc["filename"]
    document_id = doc["id"]

    if kind in ("page", "part"):
        number = _number(value, kind)
        with _database(run):
            section = repo.get_section(document_id, kind, number)
        if section is None:
            raise ToolError(_out_of_range(run, repo, doc, kind, f"{kind} {number}"))
        units, numbers = list(section["units"]), None
        locator, loc = section["locator"], {kind: number}
    elif kind in ("row", "rows", "record", "records"):
        single = "row" if kind.startswith("row") else "record"
        plural = f"{single}s"
        start, end = _range(value, plural)
        if end - start + 1 > settings.read_max_rows:
            raise ToolError(
                f"Range too large: {end - start + 1} {plural} requested; read at most "
                f"{settings.read_max_rows} per call (for example "
                f"{plural}:{start}-{start + settings.read_max_rows - 1})."
            )
        with _database(run):
            rows = repo.get_sections_in_range(document_id, single, start, end)
        if not rows:
            raise ToolError(_out_of_range(run, repo, doc, single, f"{plural} {start}-{end}"))
        units = [row["units"][0] for row in rows]
        numbers = [int(row["number"]) for row in rows]
        first, last = numbers[0], numbers[-1]
        if first == last:
            locator, loc = f"{plural}:{first}", {single: first}
        else:
            locator, loc = f"{plural}:{first}-{last}", {plural: f"{first}–{last}"}
    else:  # section
        with _database(run):
            matches = repo.find_heading_sections(document_id, value)
        if not matches:
            raise ToolError(
                f'No section named "{value}" in {name}. Call list_documents() to see its '
                "headings, and use the heading text or the full path (Parent › Child)."
            )
        if len(matches) > 1:
            candidates = "; ".join(m["locator"].removeprefix("section:") for m in matches[:10])
            raise ToolError(
                f'Several sections match "{value}" in {name}: {candidates}. Use the full '
                "heading path."
            )
        section = matches[0]
        units, numbers = list(section["units"]), None
        locator, loc = section["locator"], {"section": section["locator"].removeprefix("section:")}

    units, numbers, note = _truncate(units, numbers, settings.read_section_max_chars, loc)
    item = run.record(
        source=f"kb://{document_id}/{locator}",
        document_id=document_id,
        document_name=name,
        locator=locator,
        location=loc,
        units=units,
        unit_numbers=numbers,
        origin="read",
    )
    return item, note


def _number(value: str, kind: str) -> int:
    if not value.isdigit():
        raise ToolError(f"{kind}:N needs a number, for example {kind}:3.")
    return int(value)


def _range(value: str, plural: str) -> tuple[int, int]:
    match = _RANGE.match(value.strip())
    if not match:
        raise ToolError(f"{plural}:A-B needs a number or a range, for example {plural}:12-18.")
    if match.group(3):
        start = end = int(match.group(3))
    else:
        start, end = int(match.group(1)), int(match.group(2))
    if start > end:
        start, end = end, start
    return start, end


def _out_of_range(run: AgentRun, repo: ReadOnlyRepository, doc: Row, kind: str, asked: str) -> str:
    plural = {"page": "pages", "part": "parts", "row": "rows", "record": "records"}[kind]
    with _database(run):
        bounds = repo.number_range(doc["id"], kind)
    if bounds is None:
        return (
            f"{doc['filename']} has no {plural} (it is a {doc['document_type']} document). "
            f"Call list_documents() to see how it can be read."
        )
    return f"{doc['filename']} has no {asked}; it has {plural} {bounds[0]}–{bounds[1]}."


def _truncate(
    units: list[str], numbers: list[int] | None, max_chars: int, location: dict[str, Any]
) -> tuple[list[str], list[int] | None, str | None]:
    total = sum(len(unit) for unit in units)
    if total <= max_chars:
        return units, numbers, None
    kept: list[str] = []
    length = 0
    for unit in units:
        if kept and length + len(unit) > max_chars:
            break
        if not kept and len(unit) > max_chars:
            kept.append(unit[:max_chars])
            length = max_chars
            break
        kept.append(unit)
        length += len(unit)
    kept_numbers = numbers[: len(kept)] if numbers else None
    hint = ""
    if numbers and kept_numbers and len(kept) < len(units):
        next_number = numbers[len(kept)]
        plural = "rows" if "row" in location or "rows" in location else "records"
        hint = f" Continue with {plural}:{next_number}-{numbers[-1]}."
    note = (
        f"[Truncated: showing {length:,} of {total:,} characters of {location_label(location)}."
        f"{hint}]"
    )
    return kept, kept_numbers, note


def _text(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _search_result(item: EvidenceItem, suffix: str = "") -> dict[str, Any]:
    title = f"{item.document_name} — {item.label}" if item.label else item.document_name
    return {
        "type": "search_result",
        "source": item.source,
        "title": title + suffix,
        "content": [_text(unit) for unit in item.units],
        "citations": {"enabled": True},
    }
