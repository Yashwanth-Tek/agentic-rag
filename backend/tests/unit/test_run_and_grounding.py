"""Unit tests for the run state, citation validation, sentence split and verdict rules."""

import threading
from uuid import uuid4

from app.agent.loop import Draft, RawCitation
from app.agent.run import AgentRun, location_label, safe_detail
from app.grounding.citations import Citation, validate_citations
from app.grounding.result import answer_result
from app.grounding.sentences import split_sentences
from app.grounding.verifier import Assessment, assess


def make_run(events=None, **overrides) -> AgentRun:
    clock = overrides.pop("clock", None)
    kwargs = {
        "max_tool_calls": 3,
        "max_time_seconds": 10,
        "emit": (events if events is not None else []).append,
        "cancel": threading.Event(),
    }
    if clock:
        kwargs["clock"] = clock
    kwargs.update(overrides)
    return AgentRun(**kwargs)


def evidence(
    run: AgentRun, units, *, numbers=None, location=None, source="kb://d/rows:2-3?chunk=1"
):
    return run.record(
        source=source,
        document_id=uuid4(),
        document_name="metrics.csv",
        locator="rows:2-3",
        location=location or {"rows": "2–3"},
        units=units,
        unit_numbers=numbers,
        origin="search",
    )


# ── AgentRun ─────────────────────────────────────────────────────────────────


def test_safe_detail_collapses_whitespace_control_characters_and_length():
    assert safe_detail("a\x00b\n\n  c") == "a b c"
    assert len(safe_detail("x" * 500)) == 120
    assert safe_detail("x" * 500).endswith("…")


def test_location_label_only_uses_recorded_keys():
    assert location_label({"page": 4}) == "Page 4"
    assert location_label({"rows": "12–18"}) == "Rows 12–18"
    assert location_label({"section": "A › B"}) == "Section: A › B"
    assert location_label({}) == ""


def test_ledger_keeps_the_first_id_for_a_repeated_source():
    run = make_run()
    first = evidence(run, ["a"])
    again = evidence(run, ["different"])
    other = evidence(run, ["b"], source="kb://d/page:1")
    assert first is again
    assert (first.id, other.id) == ("E1", "E2")
    assert first.units == ["a"]  # the first recording wins


def test_limits_and_stop_reason_emit_one_limit_activity():
    events = []
    now = [0.0]
    run = make_run(events, clock=lambda: now[0])
    assert run.budget_left() and not run.over_deadline()
    run.tool_calls = 3
    assert not run.budget_left()
    now[0] = 11
    assert run.over_deadline()
    run.stop("time")
    run.stop("tool_calls")  # the first reason wins
    assert run.stopped_by == "time"
    labels = [
        e.get("label") for e in events if e["event"] == "activity" and e["status"] == "running"
    ]
    assert labels == ["Time limit reached"]


def test_activity_events_carry_ids_and_sanitised_detail():
    events = []
    run = make_run(events)
    activity = run.activity_start("search", "Searching knowledge base", "q\nwith\tnewlines")
    run.activity_done(activity, results=2)
    run.activity_failed(activity, "boom\x00")
    assert events[0] == {
        "event": "activity",
        "id": activity,
        "kind": "search",
        "status": "running",
        "label": "Searching knowledge base",
        "detail": "q with newlines",
    }
    assert events[1] == {"event": "activity", "id": activity, "status": "done", "results": 2}
    assert events[2]["status"] == "failed" and events[2]["error"] == "boom"


def test_consecutive_failures_reset_on_success():
    run = make_run()
    run.note_result(failed=True)
    run.note_result(failed=True)
    assert run.consecutive_failures == 2
    run.note_result(failed=False)
    assert run.consecutive_failures == 0


# ── Citation validation ──────────────────────────────────────────────────────


def test_citations_are_kept_only_when_they_match_the_ledger():
    run = make_run()
    item = evidence(run, ["Row two text", "Row three text"], numbers=[2, 3])
    draft = Draft(
        "A sentence. Another.",
        [
            RawCitation(0, 11, item.source, "Row two text", 0, 1),  # valid
            RawCitation(0, 11, "kb://unknown", "Row two text", 0, 1),  # unknown source
            RawCitation(0, 11, item.source, "Row two text", 0, 5),  # range out of bounds
            RawCitation(0, 11, item.source, "Something else", 0, 1),  # text mismatch
            RawCitation(
                12, 20, item.source, "Row two text\nRow three text", 0, 2
            ),  # whitespace tolerant
        ],
        usable=True,
    )
    valid = validate_citations(draft, run)
    assert [(c.start, c.unit_start, c.unit_end) for c in valid] == [(0, 0, 1), (12, 0, 2)]
    assert valid[0].location() == {"row": 2}
    assert valid[1].location() == {"rows": "2–3"}


def test_prose_citation_keeps_the_section_location():
    run = make_run()
    item = evidence(run, ["Para one"], location={"page": 4}, source="kb://d/page:4?chunk=2")
    citation = Citation(0, 5, item, "Para one", 0, 1)
    assert citation.location() == {"page": 4}


# ── Sentences ────────────────────────────────────────────────────────────────


def test_sentences_link_overlapping_citations_and_paragraphs():
    run = make_run()
    item = evidence(run, ["u1", "u2"], numbers=[2, 3])
    other = evidence(run, ["v"], source="kb://d/page:1")
    c1 = Citation(0, 14, item, "u1", 0, 1)
    c2 = Citation(15, 30, other, "v", 0, 1)
    c3 = Citation(15, 30, item, "u2", 1, 2)
    text = "First is here. Second here too.\nThird line!"
    sentences = split_sentences(text, [c1, c2, c3])
    assert [s.text for s in sentences] == ["First is here.", "Second here too.", "Third line!"]
    assert sentences[0].sources == [item.source]
    assert sentences[1].sources == [other.source, item.source]
    assert sentences[2].sources == []
    assert [s.paragraph_start for s in sentences] == [True, False, True]


# ── Verdict rules ────────────────────────────────────────────────────────────


def _sentence(text, cited):
    run = make_run()
    item = evidence(run, ["x"])
    citations = [Citation(0, len(text), item, "x", 0, 1)] if cited else []
    from app.grounding.sentences import Sentence

    return Sentence(text, citations, True)


def test_assess_rules():
    s_cited, s_uncited = _sentence("Fact.", True), _sentence("Claim.", False)
    assert assess([s_cited], ["supported"]).status == "answered"
    assert assess([s_cited, s_uncited], ["supported", "not_in_kb"]).status == "partial"
    assert assess([s_uncited], ["supported"]).status == "rejected"  # supported needs a citation
    assert assess([s_cited, s_uncited], ["supported", "unsupported"]).status == "rejected"
    assert assess([s_uncited], ["not_in_kb"]).status == "not_found"
    assert assess([s_cited], ["no_claim"]).status == "not_found"
    assert assess([s_cited], None).status == "rejected"
    assert assess([s_cited, s_uncited], ["supported"]).status == "rejected"  # count mismatch


# ── Result assembly ──────────────────────────────────────────────────────────


def test_answer_result_numbers_sources_in_order_and_builds_them_from_the_ledger():
    run = make_run()
    rows = evidence(
        run, ["Dept: Cardiology | Rate: 12.6", "Dept: Oncology | Rate: 10.9"], numbers=[13, 14]
    )
    page = evidence(run, ["Target is 12.0%."], location={"page": 4}, source="kb://d/page:4")
    text = "Cardiology was above target. Oncology was below. Nothing on June."
    c_page = Citation(0, 28, page, "Target is 12.0%.", 0, 1)
    c_row1 = Citation(0, 28, rows, "Dept: Cardiology | Rate: 12.6", 0, 1)
    c_row2 = Citation(29, 48, rows, "Dept: Oncology | Rate: 10.9", 1, 2)
    sentences = split_sentences(text, [c_page, c_row1, c_row2])
    assessment = Assessment(
        "partial", list(zip(sentences, ["supported", "supported", "not_in_kb"], strict=True))
    )
    result = answer_result(assessment, run, attempts=1)
    assert result["status"] == "partial"
    assert [(s["kind"], s["sources"]) for s in result["segments"]] == [
        ("supported", [1, 2]),
        ("supported", [2]),
        ("not_in_kb", []),
    ]
    assert [s["document_name"] for s in result["sources"]] == ["metrics.csv", "metrics.csv"]
    assert result["sources"][0]["label"] == "Page 4"
    assert result["sources"][1]["location"] == {"rows": "13–14"}
    assert result["sources"][1]["label"] == "Rows 13–14"
    assert (
        "Cardiology" in result["sources"][1]["excerpt"]
        and "Oncology" in result["sources"][1]["excerpt"]
    )
    assert result["run"]["attempts"] == 1 and result["run"]["evidence"] == 2
