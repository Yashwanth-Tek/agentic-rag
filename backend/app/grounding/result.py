"""Builds the one `result` event the UI receives: validated segments plus sources taken from the
evidence ledger (document names and locations from the database, excerpts from the API's
cited_text), never from model prose."""

from typing import Any

from app.agent.run import AgentRun, location_label
from app.grounding.citations import Citation
from app.grounding.verifier import Assessment

Event = dict[str, Any]

NOT_FOUND_MESSAGE = (
    "I couldn't find enough information in the provided knowledge base to answer this question."
)
EMPTY_KB_MESSAGE = (
    "Your knowledge base has no searchable documents yet. Upload documents on the "
    "Knowledge Base page, then ask again."
)
UNVERIFIED_MESSAGE = (
    "I found related passages in your documents, but couldn't write an answer in which every "
    "statement is verified."
)


def result_event(
    status: str,
    *,
    message: str | None = None,
    segments: list[Event] = (),
    sources: list[Event] = (),
    run: AgentRun | None = None,
    attempts: int = 0,
) -> Event:
    return {
        "event": "result",
        "status": status,
        "message": message,
        "segments": list(segments),
        "sources": list(sources),
        "run": run.summary(attempts) if run else None,
    }


def answer_result(assessment: Assessment, run: AgentRun, attempts: int) -> Event:
    """Supported sentences with their source numbers, plus not_in_kb sentences, in order."""
    numbers: dict[str, int] = {}  # evidence source → 1-based source number, in answer order
    cited: dict[str, list[Citation]] = {}
    segments = []
    for sentence, verdict in assessment.sentences:
        if verdict == "supported":
            ids = []
            for source in sentence.sources:
                ids.append(numbers.setdefault(source, len(numbers) + 1))
            for citation in sentence.citations:
                cited.setdefault(citation.evidence.source, []).append(citation)
            segments.append(_segment("supported", sentence.text, ids, sentence.paragraph_start))
        elif verdict == "not_in_kb":
            segments.append(_segment("not_in_kb", sentence.text, [], sentence.paragraph_start))
    sources = _sources(numbers, cited, run)
    return result_event(
        assessment.status, segments=segments, sources=sources, run=run, attempts=attempts
    )


def unverified_result(assessment: Assessment, run: AgentRun, attempts: int) -> Event:
    """Only the passages behind the sentences that did pass: document words, no draft text."""
    numbers: dict[str, int] = {}
    cited: dict[str, list[Citation]] = {}
    for sentence, verdict in assessment.sentences:
        if verdict == "supported":
            for source in sentence.sources:
                numbers.setdefault(source, len(numbers) + 1)
            for citation in sentence.citations:
                cited.setdefault(citation.evidence.source, []).append(citation)
    return result_event(
        "unverified",
        message=UNVERIFIED_MESSAGE,
        sources=_sources(numbers, cited, run),
        run=run,
        attempts=attempts,
    )


def _sources(
    numbers: dict[str, int], cited: dict[str, list[Citation]], run: AgentRun
) -> list[Event]:
    sources = []
    for source, number in numbers.items():
        item = run.ledger[source]
        citations = cited.get(source, [])
        location = _union_location(citations) if citations else dict(item.location)
        excerpts = dict.fromkeys(c.cited_text.strip() for c in citations)
        sources.append(
            {
                "id": number,
                "evidence_id": item.id,
                "document_id": str(item.document_id),
                "document_name": item.document_name,
                "location": location,
                "label": location_label(location),
                "excerpt": " … ".join(e for e in excerpts if e),
            }
        )
    return sources


def _union_location(citations: list[Citation]) -> dict[str, Any]:
    """One location covering every cited unit of this evidence item."""
    item = citations[0].evidence
    if item.unit_numbers:
        cited = sorted({n for c in citations for n in item.unit_numbers[c.unit_start : c.unit_end]})
        if cited:
            key = "row" if "row" in item.location or "rows" in item.location else "record"
            if cited[0] == cited[-1]:
                return {key: cited[0]}
            return {f"{key}s": f"{cited[0]}–{cited[-1]}"}
    return dict(item.location)


def _segment(kind: str, text: str, sources: list[int], paragraph_start: bool) -> Event:
    return {"kind": kind, "text": text, "sources": sources, "paragraph_start": paragraph_start}
