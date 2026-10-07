"""Per-question state shared by the tools and the loop: limits, the evidence ledger, activity.

Nothing here is reachable from the model. Tools get a reference to the run so they can record
evidence and emit activity; the limits are read, never written, by them.
"""

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.errors import AppError

Event = dict[str, Any]

MAX_DETAIL_CHARS = 120
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def safe_detail(text: str) -> str:
    """A model- or document-derived string made safe for an activity event: one line, bounded."""
    text = " ".join(_CONTROL_CHARS.sub(" ", text).split())
    if len(text) > MAX_DETAIL_CHARS:
        return text[: MAX_DETAIL_CHARS - 1] + "…"
    return text


def location_label(location: dict[str, Any]) -> str:
    """Human-readable source location, built only from metadata the parser recorded."""
    templates = {
        "page": "Page {}",
        "section": "Section: {}",
        "row": "Row {}",
        "rows": "Rows {}",
        "record": "Record {}",
        "records": "Records {}",
        "part": "Part {}",
    }
    for key, template in templates.items():
        if key in location:
            return template.format(location[key])
    return ""


@dataclass(frozen=True)
class EvidenceItem:
    id: str  # "E7": the order of first appearance in this run
    source: str  # the exact `source` string sent to Claude; the lookup key for citations
    document_id: UUID
    document_name: str
    locator: str
    location: dict[str, Any]
    units: list[str]  # the text blocks sent, in order
    unit_numbers: list[int] | None  # row / record number per unit, when known
    origin: str  # "search" | "read"

    @property
    def label(self) -> str:
        return location_label(self.location)


class AgentRun:
    def __init__(
        self,
        *,
        max_tool_calls: int,
        max_time_seconds: float,
        emit: Callable[[Event], None],
        cancel: threading.Event | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_tool_calls = max_tool_calls
        self.max_time_seconds = max_time_seconds
        self._emit = emit
        self._cancel = cancel or threading.Event()
        self._clock = clock
        self.started = clock()
        self.tool_calls = 0
        self.consecutive_failures = 0
        self.stopped_by: str | None = None  # "tool_calls" | "time" | "failures"
        self.fatal: AppError | None = None
        self.ledger: dict[str, EvidenceItem] = {}
        self._next_activity = 0

    # ── Limits ───────────────────────────────────────────────────────────────

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def elapsed_seconds(self) -> float:
        return self._clock() - self.started

    def over_deadline(self) -> bool:
        return self.elapsed_seconds() >= self.max_time_seconds

    def budget_left(self) -> bool:
        return self.tool_calls < self.max_tool_calls

    def stop(self, reason: str) -> None:
        """Record why retrieval ended early (the first reason wins) and tell the UI once."""
        if self.stopped_by is None:
            self.stopped_by = reason
            labels = {
                "tool_calls": "Retrieval limit reached",
                "time": "Time limit reached",
                "failures": "Stopped after repeated tool failures",
            }
            activity = self.activity_start("limit", labels.get(reason, "Stopped early"))
            self.activity_done(activity)

    def note_result(self, *, failed: bool) -> None:
        self.consecutive_failures = self.consecutive_failures + 1 if failed else 0

    # ── Evidence ledger ──────────────────────────────────────────────────────

    def record(
        self,
        *,
        source: str,
        document_id: UUID,
        document_name: str,
        locator: str,
        location: dict[str, Any],
        units: list[str],
        unit_numbers: list[int] | None,
        origin: str,
    ) -> EvidenceItem:
        """Add evidence returned by a tool. The same source keeps its first id."""
        existing = self.ledger.get(source)
        if existing is not None:
            return existing
        item = EvidenceItem(
            id=f"E{len(self.ledger) + 1}",
            source=source,
            document_id=document_id,
            document_name=document_name,
            locator=locator,
            location=dict(location),
            units=list(units),
            unit_numbers=list(unit_numbers) if unit_numbers else None,
            origin=origin,
        )
        self.ledger[source] = item
        return item

    # ── Activity events (what the UI shows; never model text) ────────────────

    def activity_start(self, kind: str, label: str, detail: str | None = None) -> int:
        self._next_activity += 1
        event: Event = {
            "event": "activity",
            "id": self._next_activity,
            "kind": kind,
            "status": "running",
            "label": label,
        }
        if detail:
            event["detail"] = safe_detail(detail)
        self._emit(event)
        return self._next_activity

    def activity_done(self, activity_id: int, **extra: Any) -> None:
        self._emit({"event": "activity", "id": activity_id, "status": "done", **extra})

    def activity_failed(self, activity_id: int, error: str) -> None:
        event = {"event": "activity", "id": activity_id, "status": "failed"}
        self._emit({**event, "error": safe_detail(error)})

    def summary(self, attempts: int) -> dict[str, Any]:
        return {
            "tool_calls": self.tool_calls,
            "elapsed_ms": round(self.elapsed_seconds() * 1000),
            "stopped_by": self.stopped_by,
            "attempts": attempts,
            "evidence": len(self.ledger),
        }
