"""Loop-level tests that need control over the clock, the repository or cancellation."""

import threading

import psycopg
from pydantic import SecretStr

from app.agent.loop import run_agent
from app.agent.run import AgentRun
from app.agent.service import answer_question
from app.db.read_repository import ReadOnlyRepository
from tests.fakes import Answer, FakeEmbedder, ToolCalls, scripted_claude


def make_run(events, cancel=None, clock=None, **limits):
    kwargs = {"max_tool_calls": 8, "max_time_seconds": 60, "emit": events.append}
    kwargs.update(limits)
    if cancel is not None:
        kwargs["cancel"] = cancel
    if clock is not None:
        kwargs["clock"] = clock
    return AgentRun(**kwargs)


def test_time_limit_stops_retrieval_and_wraps_up(repo, settings, test_database_url):
    now = [0.0]
    events = []
    run = make_run(events, clock=lambda: now[0], max_time_seconds=30)

    def slow_turn(_request):
        now[0] += 31  # the first Claude request "took" longer than the whole budget
        return ToolCalls([("search_knowledge_base", {"query": "anything"})])

    llm = scripted_claude([slow_turn, Answer([("Nothing found.", [])])])
    outcome = run_agent(
        "q",
        run=run,
        repo=repo.read_only(),
        embedder=FakeEmbedder(),
        llm=llm,
        settings=settings.model_copy(update={"database_url": SecretStr(test_database_url)}),
    )

    assert outcome.kind == "limit"
    assert run.stopped_by == "time"
    assert run.tool_calls == 0  # the deadline check runs before any tool executes
    [wrap_up] = llm.script.create_requests
    assert wrap_up["tool_choice"] == {"type": "none"}
    labels = [e.get("label") for e in events if e.get("status") == "running"]
    assert "Time limit reached" in labels and "Preparing answer" in labels


def test_cancellation_stops_the_run_without_a_result(repo, settings):
    cancel = threading.Event()
    events = []
    run = make_run(events, cancel=cancel)

    def cancelling_turn(_request):
        cancel.set()  # the client went away while Claude was answering
        return ToolCalls([("list_documents", {})])

    llm = scripted_claude([cancelling_turn, Answer([("x", [])])])
    outcome = run_agent(
        "q", run=run, repo=repo.read_only(), embedder=FakeEmbedder(), llm=llm, settings=settings
    )

    assert outcome.kind == "cancelled"
    assert run.tool_calls == 0
    assert llm.script.create_requests == []
    assert not any(e.get("event") == "result" for e in events)


class BrokenRepository(ReadOnlyRepository):
    def has_searchable_documents(self, embedding_model: str) -> bool:
        return True

    def search_chunks(self, *args, **kwargs):
        raise psycopg.OperationalError("connection lost")

    def list_documents(self):
        raise psycopg.OperationalError("connection lost")


def test_database_outage_during_a_tool_call_is_fatal(repo, settings, collect):
    events, emit, cancel = collect
    llm = scripted_claude(
        [
            ToolCalls([("search_knowledge_base", {"query": "x"})]),
            ToolCalls([("list_documents", {})]),  # never reached
            Answer([("x", [])]),
        ]
    )
    answer_question(
        "q",
        cancel=cancel,
        emit=emit,
        repo=BrokenRepository(repo.pool),
        embedder=FakeEmbedder(),
        llm=llm,
        settings=settings,
    )

    final = events[-1]
    assert final["event"] == "error" and final["code"] == "DATABASE_UNAVAILABLE"
    assert len(llm.script.agent_requests) == 1
    failed = [e for e in events if e.get("status") == "failed"]
    assert failed and "database" in failed[0]["error"].lower()
