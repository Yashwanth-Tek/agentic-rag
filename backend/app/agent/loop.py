"""The agent loop: Claude decides which tools to call; the SDK tool runner drives the cycle; this
module enforces the limits around it and produces a Draft for the guardrails.

The runner yields every assistant turn *before* the tools run, so each turn is a checkpoint:
cancellation, the deadline, repeated failures and fatal errors are all checked here. When the
loop ends without an answer (a limit was hit), one more request with tools disabled asks for an
answer from the evidence already retrieved.
"""

import logging
from dataclasses import dataclass
from typing import Any

import anthropic

from app.agent.prompts import AGENT_SYSTEM_PROMPT, REJECTED_SENTENCES_NOTE, RETRY_NOTE, WRAP_UP_NOTE
from app.agent.run import AgentRun
from app.agent.tools import make_tools
from app.config import Settings
from app.db.read_repository import ReadOnlyRepository
from app.embeddings.provider import EmbeddingProvider
from app.llm import FALLBACK_BETA, to_app_error

log = logging.getLogger(__name__)

MAX_ANSWER_TOKENS = 16000
NO_TOOLS = {"type": "none"}


@dataclass(frozen=True)
class RawCitation:
    start: int  # character span in Draft.text this citation supports
    end: int
    source: str  # the `source` of the cited search_result block
    cited_text: str  # the exact cited text, extracted by the API (never by the model)
    unit_start: int  # cited block range inside that source's content
    unit_end: int


@dataclass(frozen=True)
class Draft:
    text: str
    citations: list[RawCitation]
    usable: bool  # False when the model declined or the answer was cut off


@dataclass
class AgentOutcome:
    kind: str  # answered | limit | unusable | fatal | cancelled
    draft: Draft | None
    history: list[dict[str, Any]]  # the conversation so far, for the wrap-up and retry calls
    tool_definitions: list[dict[str, Any]]


def request_params(settings: Settings) -> dict[str, Any]:
    return {
        "model": settings.anthropic_model,
        "max_tokens": MAX_ANSWER_TOKENS,
        "system": [{"type": "text", "text": AGENT_SYSTEM_PROMPT}],
        "output_config": {"effort": settings.anthropic_effort},
        "betas": [FALLBACK_BETA],
        "fallbacks": "default",
        "cache_control": {"type": "ephemeral"},
    }


def run_agent(
    question: str,
    *,
    run: AgentRun,
    repo: ReadOnlyRepository,
    embedder: EmbeddingProvider,
    llm: anthropic.Anthropic,
    settings: Settings,
) -> AgentOutcome:
    tools = make_tools(run, repo, embedder, settings)
    tool_definitions = [tool.to_dict() for tool in tools]
    history: list[dict[str, Any]] = [
        {"role": "user", "content": [{"type": "text", "text": f"Question: {question}"}]}
    ]
    analyze: int | None = run.activity_start("analyze", "Understanding question")
    review: int | None = None
    final = None
    try:
        runner = llm.beta.messages.tool_runner(
            tools=tools,
            messages=list(history),
            max_iterations=settings.max_tool_calls + 1,
            **request_params(settings),
        )
        for message in runner:
            analyze = _finish(run, analyze)
            review = _finish(run, review)
            history.append(message.to_param())
            if message.stop_reason in ("refusal", "max_tokens"):
                log.warning("agent turn not usable", extra={"stop_reason": message.stop_reason})
                return AgentOutcome("unusable", None, history, tool_definitions)
            if not any(block.type == "tool_use" for block in message.content):
                final = message
                break
            if run.cancelled:
                return AgentOutcome("cancelled", None, history, tool_definitions)
            # Runs this turn's tools now (the runner reuses the cached result), so activity
            # events stream in real time and failures are visible before the next request.
            response = runner.generate_tool_call_response()
            if response is None:
                final = message
                break
            history.append(response)
            for block in response["content"]:
                run.note_result(failed=bool(block.get("is_error")))
            if run.cancelled:
                return AgentOutcome("cancelled", None, history, tool_definitions)
            if run.fatal is not None:
                return AgentOutcome("fatal", None, history, tool_definitions)
            if run.stopped_by:  # a tool reported that the budget or the deadline was hit
                break
            if run.consecutive_failures >= settings.max_consecutive_tool_failures:
                run.stop("failures")
                break
            if run.over_deadline():
                run.stop("time")
                break
            review = run.activity_start("review", "Reviewing retrieved information")
        else:
            # The runner reached max_iterations: results were sent back, no answer came.
            run.stop("tool_calls")
    except anthropic.APIError as exc:
        raise to_app_error(exc) from exc
    finally:
        _finish(run, analyze)
        _finish(run, review)

    if final is not None:
        return AgentOutcome("answered", draft_from(final), history, tool_definitions)
    if run.cancelled:
        return AgentOutcome("cancelled", None, history, tool_definitions)
    draft = _answer_without_tools(
        llm, settings, run, history, tool_definitions, WRAP_UP_NOTE, "Preparing answer"
    )
    return AgentOutcome("limit", draft, history, tool_definitions)


def retry_answer(
    llm: anthropic.Anthropic,
    settings: Settings,
    run: AgentRun,
    outcome: AgentOutcome,
    rejected: list[str],
) -> Draft:
    """Ask once more, in the same conversation, listing the rejected sentences. No tools."""
    note = RETRY_NOTE
    if rejected:
        note += REJECTED_SENTENCES_NOTE.format(sentences="\n".join(f"- {s}" for s in rejected))
    return _answer_without_tools(
        llm, settings, run, outcome.history, outcome.tool_definitions, note, "Revising answer"
    )


def _answer_without_tools(
    llm: anthropic.Anthropic,
    settings: Settings,
    run: AgentRun,
    history: list[dict[str, Any]],
    tool_definitions: list[dict[str, Any]],
    note: str,
    label: str,
) -> Draft:
    activity = run.activity_start("answer", label)
    history.append({"role": "user", "content": [{"type": "text", "text": note}]})
    try:
        message = llm.beta.messages.create(
            messages=list(history),
            tools=tool_definitions,  # declared so the history validates; disabled below
            tool_choice=NO_TOOLS,
            **request_params(settings),
        )
    except anthropic.APIError as exc:
        run.activity_failed(activity, "The AI service failed")
        raise to_app_error(exc) from exc
    history.append(message.to_param())
    run.activity_done(activity)
    return draft_from(message)


def draft_from(message: Any) -> Draft:
    if message.stop_reason in ("refusal", "max_tokens"):
        log.warning("answer not usable", extra={"stop_reason": message.stop_reason})
        return Draft("", [], usable=False)
    text = ""
    citations: list[RawCitation] = []
    for block in message.content:
        if block.type != "text":
            continue
        start = len(text)
        text += block.text
        for citation in block.citations or []:
            if citation.type == "search_result_location":
                citations.append(
                    RawCitation(
                        start,
                        len(text),
                        citation.source,
                        citation.cited_text,
                        citation.start_block_index,
                        citation.end_block_index,
                    )
                )
    return Draft(text, citations, usable=True)


def _finish(run: AgentRun, activity: int | None) -> None:
    if activity is not None:
        run.activity_done(activity)
    return None
