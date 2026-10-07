import json

import pytest

from app.errors import AppError
from app.ingestion.extractors import extract
from app.ingestion.sections import (
    HeadingSectionBuilder,
    normalize_text,
    paragraphs,
    part_sections,
    split_long,
)
from tests.fakes import make_docx, make_pdf

PART = 4000


def test_normalize_text_unifies_whitespace_and_drops_invisible_characters():
    assert normalize_text("a\r\nb​  c\n\n\n\nd\t") == "a\nb c\n\nd"


def test_paragraphs_are_blank_line_separated_units_with_content():
    assert paragraphs("One.\n\n  \n\nTwo\nlines.\n\n---\n") == ["One.", "Two\nlines."]


def test_split_long_prefers_sentence_then_word_boundaries():
    text = "First sentence here. Second sentence here. Third one."
    assert split_long(text, 25) == ["First sentence here.", "Second sentence here.", "Third one."]
    assert split_long("word " * 10, 12) == [
        "word word",
        "word word",
        "word word",
        "word word",
        "word word",
    ]
    assert split_long("x" * 30, 10) == ["x" * 10] * 3


def test_part_sections_group_paragraphs_and_number_parts():
    text = "\n\n".join(f"Paragraph {i} " + "words " * 50 for i in range(6))
    parts = part_sections(text, 700)
    assert [p.locator for p in parts] == [f"part:{n}" for n in range(1, len(parts) + 1)]
    assert sum(len(p.units) for p in parts) == 6
    assert all(sum(len(u) for u in p.units) <= 700 + 2 * len(p.units) for p in parts)


def test_heading_builder_records_paths_and_preamble():
    builder = HeadingSectionBuilder(PART)
    builder.add_line("Intro text before any heading.")
    builder.start_heading(1, "Policy")
    builder.add_line("Top level body.")
    builder.start_heading(2, "Scope")
    builder.add_line("Scope body.")
    builder.start_heading(2, "Scope")  # duplicate path
    builder.add_line("Second scope body.")
    builder.start_heading(1, "Empty heading")
    builder.start_heading(2, "Child")
    builder.add_line("Child body.")
    sections = builder.finish()
    assert [s.locator for s in sections] == [
        "part:1",
        "section:Policy",
        "section:Policy › Scope",
        "section:Policy › Scope (2)",
        "section:Empty heading › Child",
    ]
    assert sections[1].label == "Section: Policy"
    assert builder.outline == [
        "Policy",
        "Policy › Scope",
        "Policy › Scope",
        "Empty heading",
        "Empty heading › Child",
    ]


def test_pdf_pages_become_page_sections_with_paragraph_units():
    data = make_pdf(["Page one text.", "", "Page three text."])
    extraction = extract("pdf", data, part_chars=PART)
    assert [s.locator for s in extraction.sections] == ["page:1", "page:3"]
    assert extraction.sections[0].units == ["Page one text."]
    assert extraction.metadata["pages"] == 3


def test_pdf_without_text_is_rejected():
    with pytest.raises(AppError) as caught:
        extract("pdf", make_pdf(["", ""]), part_chars=PART)
    assert caught.value.code == "NO_TEXT"
    assert "Scanned" in caught.value.message


def test_docx_headings_become_sections_and_tables_keep_order():
    data = make_docx(
        [
            ("h1", "Benefits"),
            ("p", "Overview paragraph."),
            ("h2", "Leave"),
            ("table", "Type|Days;Annual|25"),
        ]
    )
    extraction = extract("docx", data, part_chars=PART)
    assert [s.locator for s in extraction.sections] == [
        "section:Benefits",
        "section:Benefits › Leave",
    ]
    assert extraction.sections[1].units == ["Type | Days\nAnnual | 25"]
    assert extraction.metadata["outline"] == ["Benefits", "Benefits › Leave"]


def test_docx_without_headings_falls_back_to_parts():
    extraction = extract(
        "docx", make_docx([("p", "Just a paragraph."), ("p", "Another.")]), part_chars=PART
    )
    assert [s.locator for s in extraction.sections] == ["part:1"]
    assert extraction.sections[0].units == ["Just a paragraph.", "Another."]


def test_markdown_headings_and_code_fences():
    text = "# Runbook\n\nIntro.\n\n## Severity levels\n\n```\n# not a heading\n```\n\nP1 is critical.\n"
    extraction = extract("md", text.encode(), part_chars=PART)
    assert [s.locator for s in extraction.sections] == [
        "section:Runbook",
        "section:Runbook › Severity levels",
    ]
    assert extraction.sections[1].units == ["```\n# not a heading\n```", "P1 is critical."]


def test_csv_rows_are_sections_numbered_like_a_spreadsheet():
    text = "Department,Month,Rate\nCardiology,June,12.6\n,,\nOncology,June,10.9\n"
    extraction = extract("csv", text.encode(), part_chars=PART)
    assert [s.locator for s in extraction.sections] == ["row:2", "row:4"]
    assert extraction.sections[0].units == ["Department: Cardiology | Month: June | Rate: 12.6"]
    assert extraction.metadata == {
        "rows": 2,
        "columns": ["Department", "Month", "Rate"],
        "row_range": "2-4",
        "characters": len(extraction.sections[0].units[0]) + len(extraction.sections[1].units[0]),
    }


def test_json_array_becomes_records_and_object_becomes_parts():
    records = json.dumps([{"name": "Telehealth", "fee": 40}, {"name": "Imaging"}]).encode()
    extraction = extract("json", records, part_chars=PART)
    assert [s.locator for s in extraction.sections] == ["record:1", "record:2"]
    assert extraction.sections[0].units == ["name: Telehealth\nfee: 40"]
    assert extraction.metadata["records"] == 2

    single = extract("json", json.dumps({"a": {"b": [1, 2]}}).encode(), part_chars=PART)
    assert single.sections[0].locator == "part:1"
    assert single.sections[0].units == ["a.b[0]: 1", "a.b[1]: 2"]  # one unit per line


def test_invalid_json_is_a_corrupted_file():
    with pytest.raises(AppError) as caught:
        extract("json", b"{not json", part_chars=PART)
    assert caught.value.code == "CORRUPTED_FILE"


def test_corrupted_pdf_is_a_corrupted_file():
    with pytest.raises(AppError) as caught:
        extract("pdf", b"%PDF-1.4 garbage", part_chars=PART)
    assert caught.value.code == "CORRUPTED_FILE"


def test_text_file_is_split_into_parts():
    text = "\n\n".join(f"Sentence number {i}. " * 20 for i in range(12))
    extraction = extract("txt", text.encode(), part_chars=1200)
    assert extraction.sections[0].locator == "part:1"
    assert len(extraction.sections) > 1
    assert extraction.metadata["parts"] == len(extraction.sections)
