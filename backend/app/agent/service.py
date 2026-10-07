"""Question → validated answer. Runs on a worker thread; everything it tells the UI goes through
`emit`: activity events while working, then exactly one `result` or `error` event.

① knowledge base empty?            → kb_empty (Claude is never called)
② agent loop (tools, limits)       → draft, or a wrap-up draft after a limit
③ citation validation              → nothing citable → not_found
④ sentence verification            → rejected → retry once (no tools) → still rejected → unverified
⑤ result built from the ledger (database facts) and the API's cited text
"""

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import anthropic
import psycopg

from app.agent.loop import Draft, retry_answer, run_agent
from app.agent.run import AgentRun, Event
from app.config import Settings
from app.db.read_repository import ReadOnlyRepository
from app.embeddings.provider import EmbeddingProvider
from app.errors import AppError
from app.grounding.citations import validate_citations
from app.grounding.result import (
    EMPTY_KB_MESSAGE,
    NOT_FOUND_MESSAGE,
    answer_result,
    result_event,
    unverified_result,
)
from app.grounding.sentences import split_sentences
from app.grounding.verifier import assess, verify

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 2


def answer_question(
    question: str,
    *,
    cancel: threading.Event,
    emit: Callable[[Event], None],
    repo: ReadOnlyRepository,
    embedder: EmbeddingProvider,
    llm: anthropic.Anthropic,
    settings: Settings,
) -> None:
    started = time.perf_counter()
    trace: dict[str, Any] = {}

    def finish(result: Event) -> None:
        trace["ms"] = round((time.perf_counter() - started) * 1000)
        log.info("question answered", extra={"status": result.get("status"), **trace})
        log.debug("question text", extra={"question": question})
        emit(result)

    try:
        if not repo.has_searchable_documents(embedder.model_id):
            finish(result_event("kb_empty", message=EMPTY_KB_MESSAGE))
            return

        run = AgentRun(
            max_tool_calls=settings.max_tool_calls,
            max_time_seconds=settings.max_agent_time_seconds,
            emit=emit,
            cancel=cancel,
        )
        outcome = run_agent(
            question, run=run, repo=repo, embedder=embedder, llm=llm, settings=settings
        )
        trace.update(tool_calls=run.tool_calls, stopped_by=run.stopped_by, outcome=outcome.kind)
        if outcome.kind == "cancelled":
            log.info("question cancelled", extra=trace)
            return
        if outcome.kind == "fatal":
            raise run.fatal or AppError("INTERNAL_ERROR", "Something went wrong.", 500)
        draft: Draft | None = outcome.draft
        if draft is None or not draft.usable:
            trace["reason"] = "model_declined"
            finish(result_event("not_found", message=NOT_FOUND_MESSAGE, run=run))
            return

        validating = run.activity_start("validate", "Validating sources")
        rejected: list[str] = []
        assessment = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            trace["attempts"] = attempt
            citations = validate_citations(draft, run)
            if not citations:
                # Nothing citable: the model found no answer, or answered from outside the KB.
                trace["reason"] = "no_citations"
                run.activity_done(validating)
                finish(
                    result_event("not_found", message=NOT_FOUND_MESSAGE, run=run, attempts=attempt)
                )
                return
            sentences = split_sentences(draft.text, citations)
            verdicts = verify(llm, settings, question, sentences, run.ledger) if sentences else []
            assessment = assess(sentences, verdicts)
            trace["verdicts"] = [v for _, v in assessment.sentences]
            if assessment.status != "rejected":
                break
            # Tell the retry why each sentence failed: most rejections are missing citations.
            rejected = [
                f"{s.text} [{'no citation' if not s.citations else 'not stated by the passages'}]"
                for s, v in assessment.sentences
                if v == "unsupported"
            ]
            log.warning("draft rejected by guardrails", extra={"attempt": attempt, **trace})
            if attempt == MAX_ATTEMPTS or run.over_deadline() or run.cancelled:
                break
            draft = retry_answer(llm, settings, run, outcome, rejected)
            if not draft.usable:
                break
        run.activity_done(validating)
        assert assessment is not None

        if assessment.status == "rejected":
            trace["reason"] = "rejected"
            finish(unverified_result(assessment, run, trace["attempts"]))
        elif assessment.status == "not_found":
            trace["reason"] = "not_found"
            finish(
                result_event(
                    "not_found", message=NOT_FOUND_MESSAGE, run=run, attempts=trace["attempts"]
                )
            )
        else:
            finish(answer_result(assessment, run, trace["attempts"]))
    except AppError as exc:
        log.warning("question failed", extra={"code": exc.code, **trace})
        emit({"event": "error", "code": exc.code, "message": exc.message})
    except psycopg.OperationalError:
        log.exception("database unavailable while answering")
        message = "The database is unavailable. Please try again shortly."
        emit({"event": "error", "code": "DATABASE_UNAVAILABLE", "message": message})
    except Exception:
        log.exception("answering failed")
        message = "Something went wrong on our side. Please try again."
        emit({"event": "error", "code": "INTERNAL_ERROR", "message": message})
