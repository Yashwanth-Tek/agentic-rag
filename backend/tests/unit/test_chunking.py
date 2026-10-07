from app.ingestion.chunking import chunk_sections
from app.ingestion.sections import Section, page_section, record_section, row_section


def test_rows_are_packed_and_remember_their_numbers():
    rows = [row_section(n, f"Department: D{n} | Rate: {n}") for n in range(2, 12)]
    chunks = chunk_sections(rows, size=80, overlap=0)
    assert len(chunks) > 1
    first = chunks[0]
    assert first.units == [r.units[0] for r in rows[: len(first.units)]]
    assert first.unit_numbers == list(range(2, 2 + len(first.units)))
    assert first.locator == f"rows:2-{1 + len(first.units)}"
    assert first.location == {"rows": f"2–{1 + len(first.units)}"}
    assert all(len(c.content) <= 80 for c in chunks)
    assert [n for c in chunks for n in c.unit_numbers] == list(range(2, 12))


def test_single_row_chunk_uses_singular_location():
    chunks = chunk_sections([row_section(5, "a: 1")], size=100, overlap=0)
    assert chunks[0].locator == "rows:5"
    assert chunks[0].location == {"row": 5}


def test_records_and_rows_never_share_a_chunk():
    sections = [row_section(2, "r: 1"), record_section(1, "x: 1")]
    chunks = chunk_sections(sections, size=100, overlap=0)
    assert [c.locator for c in chunks] == ["rows:2", "records:1"]


def test_prose_chunks_stay_inside_their_section_and_overlap_whole_units():
    page = page_section(3, "Alpha one.\n\nBeta two.\n\nGamma three.\n\nDelta four.")
    chunks = chunk_sections([page], size=24, overlap=12)
    assert all(c.location == {"page": 3} and c.locator == "page:3" for c in chunks)
    assert chunks[0].units == ["Alpha one.", "Beta two."]
    assert chunks[1].units[0] == "Beta two."  # the overlap repeats a whole unit
    assert all(c.unit_numbers is None for c in chunks)


def test_long_unit_is_split_into_pieces():
    section = Section("section", None, "section:Big", "Section: Big", ["word " * 60])
    chunks = chunk_sections([section], size=100, overlap=0)
    assert len(chunks) >= 3
    assert all(len(u) <= 100 for c in chunks for u in c.units)
    assert chunks[0].location == {"section": "Big"}


def test_part_sections_keep_their_part_number():
    section = Section("part", 2, "part:2", "Part 2", ["one", "two"])
    assert chunk_sections([section], 100, 0)[0].location == {"part": 2}
