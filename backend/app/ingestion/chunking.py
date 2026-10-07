"""Cuts sections into chunks for the search index.

A chunk never crosses a section boundary, so its page / heading / part is exact. Consecutive
CSV rows and JSON records are packed together (one row is too small to retrieve well on its
own); such a chunk remembers the row number of every unit, so a citation on one of its units
maps back to the exact rows.
"""

from dataclasses import dataclass

from app.ingestion.sections import Section, split_long

_PACKED_KINDS = {"row": "rows", "record": "records"}


@dataclass(frozen=True)
class Chunk:
    content: str
    units: list[str]  # citable units, in order
    unit_numbers: list[int] | None  # row/record number per unit for packed chunks
    locator: str  # read_section location covering this chunk
    location: dict[str, str | int]  # what the UI shows, e.g. {"page": 4} or {"rows": "12–18"}


def chunk_sections(sections: list[Section], size: int, overlap: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    group: list[Section] = []

    def close_group() -> None:
        if group:
            chunks.extend(_pack_records(group, size))
            group.clear()

    for section in sections:
        if section.kind in _PACKED_KINDS:
            if group and group[0].kind != section.kind:
                close_group()
            group.append(section)
            continue
        close_group()
        chunks.extend(_split_prose(section, size, overlap))
    close_group()
    return chunks


def _pack_records(sections: list[Section], size: int) -> list[Chunk]:
    kind = sections[0].kind
    plural = _PACKED_KINDS[kind]
    chunks: list[Chunk] = []
    units: list[str] = []
    numbers: list[int] = []
    length = 0

    def close() -> None:
        if not units:
            return
        first, last = numbers[0], numbers[-1]
        if first == last:
            locator, location = f"{plural}:{first}", {kind: first}
        else:
            locator, location = f"{plural}:{first}-{last}", {plural: f"{first}–{last}"}
        chunks.append(Chunk("\n".join(units), list(units), list(numbers), locator, location))
        units.clear()
        numbers.clear()

    for section in sections:
        text = section.units[0]
        if units and length + len(text) + 1 > size:
            close()
            length = 0
        units.append(text)
        numbers.append(int(section.number or 0))
        length += len(text) + 1
    close()
    return chunks


def _split_prose(section: Section, size: int, overlap: int) -> list[Chunk]:
    pieces = [piece for unit in section.units for piece in split_long(unit, size)]
    location = _prose_location(section)
    chunks: list[Chunk] = []
    current: list[str] = []
    length = 0
    for piece in pieces:
        if current and length + len(piece) + 1 > size:
            chunks.append(_prose_chunk(current, section, location))
            current, length = _tail(current, overlap)
            while current and length + len(piece) + 1 > size:
                length -= len(current.pop(0)) + 1
        current.append(piece)
        length += len(piece) + 1
    if current:
        chunks.append(_prose_chunk(current, section, location))
    return chunks


def _prose_chunk(units: list[str], section: Section, location: dict) -> Chunk:
    return Chunk("\n".join(units), list(units), None, section.locator, location)


def _prose_location(section: Section) -> dict[str, str | int]:
    if section.kind == "page":
        return {"page": int(section.number or 0)}
    if section.kind == "part":
        return {"part": int(section.number or 0)}
    return {"section": section.locator.removeprefix("section:")}


def _tail(pieces: list[str], overlap: int) -> tuple[list[str], int]:
    """The trailing whole pieces that fit in `overlap` characters, repeated in the next chunk."""
    tail: list[str] = []
    length = 0
    for piece in reversed(pieces):
        if length + len(piece) + 1 > overlap:
            break
        tail.insert(0, piece)
        length += len(piece) + 1
    return tail, length
