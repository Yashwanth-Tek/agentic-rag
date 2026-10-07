"""Citation validation: a citation is accepted only if it points at evidence the tools returned.

The model never writes citations; the API attaches them to the search_result blocks the tools
sent. This module still checks every one against the run's ledger (source known, block range in
bounds, cited text equal to the ledger's units), and derives the location shown to the user from
the ledger, never from model text.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any

from app.agent.loop import Draft
from app.agent.run import AgentRun, EvidenceItem

log = logging.getLogger(__name__)

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Citation:
    start: int  # character span in the draft text
    end: int
    evidence: EvidenceItem
    cited_text: str
    unit_start: int
    unit_end: int

    def location(self) -> dict[str, Any]:
        """The evidence item's location, narrowed to the cited rows/records when known."""
        numbers = self.evidence.unit_numbers
        if numbers:
            cited = numbers[self.unit_start : self.unit_end]
            if cited:
                location = self.evidence.location
                key = "row" if "row" in location or "rows" in location else "record"
                if cited[0] == cited[-1]:
                    return {key: cited[0]}
                return {f"{key}s": f"{cited[0]}–{cited[-1]}"}
        return dict(self.evidence.location)


def validate_citations(draft: Draft, run: AgentRun) -> list[Citation]:
    valid: list[Citation] = []
    for raw in draft.citations:
        item = run.ledger.get(raw.source)
        if item is None:
            log.warning("citation dropped: unknown source", extra={"source": raw.source[:120]})
            continue
        if not 0 <= raw.unit_start < raw.unit_end <= len(item.units):
            log.warning("citation dropped: block range out of bounds", extra={"evidence": item.id})
            continue
        expected = _squash("".join(item.units[raw.unit_start : raw.unit_end]))
        if _squash(raw.cited_text) != expected:
            log.warning("citation dropped: cited text mismatch", extra={"evidence": item.id})
            continue
        valid.append(
            Citation(raw.start, raw.end, item, raw.cited_text, raw.unit_start, raw.unit_end)
        )
    return valid


def _squash(text: str) -> str:
    return _WHITESPACE.sub("", text)
