"""Sections: the locator-addressable units a document is stored as.

A section is a page, a heading section, a CSV row, a JSON record, or a part of an unstructured
text. Each carries a locator the agent can use with read_section (`page:4`, `section:A › B`,
`row:13`, `record:3`, `part:2`) and a list of citable units (paragraphs, or the single row /
record text), so a citation can always be traced to an exact place that the parser recorded.
"""

import re
import unicodedata
from dataclasses import dataclass

HEADING_SEPARATOR = " › "

_BLANK_LINES = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Section:
    kind: str  # page | section | row | record | part
    number: int | None  # page / row / record / part number; None for heading sections
    locator: str
    label: str
    units: list[str]


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0e-\x1f\x7f­​﻿]")
_HORIZONTAL_SPACE = re.compile(r"[ \t\f\v ]+")
_MANY_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """Unify line endings and Unicode form, drop invisible characters, collapse spacing."""
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = _CONTROL_CHARS.sub("", text)
    lines = (_HORIZONTAL_SPACE.sub(" ", line).strip() for line in text.split("\n"))
    return _MANY_BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def has_text(text: str) -> bool:
    return any(ch.isalnum() for ch in text)


def paragraphs(text: str) -> list[str]:
    """Citable units of a prose text: blank-line separated paragraphs with real content."""
    return [p.strip() for p in _BLANK_LINES.split(normalize_text(text)) if has_text(p)]


def split_long(text: str, size: int) -> list[str]:
    """Cut a single over-long unit into pieces of at most `size` characters, preferring
    sentence boundaries, then word boundaries, then hard cuts."""
    if len(text) <= size:
        return [text]
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        if len(sentence) > size:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_split_words(sentence, size))
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) > size:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _split_words(text: str, size: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for word in text.split(" "):
        while len(word) > size:  # a single token longer than the limit: hard cut
            if current:
                pieces.append(current)
                current = ""
            pieces.append(word[:size])
            word = word[size:]
        candidate = f"{current} {word}".strip() if current else word
        if len(candidate) > size:
            pieces.append(current)
            current = word
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


# ── Builders ─────────────────────────────────────────────────────────────────


def page_section(number: int, text: str) -> Section | None:
    units = paragraphs(text)
    return Section("page", number, f"page:{number}", f"Page {number}", units) if units else None


def row_section(number: int, text: str) -> Section:
    return Section("row", number, f"row:{number}", f"Row {number}", [normalize_text(text)])


def record_section(number: int, text: str) -> Section:
    return Section("record", number, f"record:{number}", f"Record {number}", [normalize_text(text)])


def part_sections(text: str, part_chars: int, start: int = 1) -> list[Section]:
    """Group paragraphs into parts of about `part_chars` characters (`part:N` locators)."""
    parts: list[list[str]] = []
    current: list[str] = []
    length = 0
    for paragraph in paragraphs(text):
        for piece in split_long(paragraph, part_chars):
            if current and length + len(piece) > part_chars:
                parts.append(current)
                current, length = [], 0
            current.append(piece)
            length += len(piece) + 2
    if current:
        parts.append(current)
    return [
        Section("part", number, f"part:{number}", f"Part {number}", units)
        for number, units in enumerate(parts, start=start)
    ]


class HeadingSectionBuilder:
    """Collects lines into sections that start at each heading and remember the heading path.

    Text before the first heading becomes `part:1`. A heading directly followed by a sub-heading
    produces no section of its own: its title is already part of the sub-section's path. A
    document without any heading falls back to parts.
    """

    def __init__(self, part_chars: int) -> None:
        self._part_chars = part_chars
        self._sections: list[Section] = []
        self._lines: list[str] = []
        self._headings: list[str] = []
        self._seen_locators: dict[str, int] = {}
        self.outline: list[str] = []

    def start_heading(self, level: int, title: str) -> None:
        self._flush()
        self._headings[level - 1 :] = [title.strip()]
        path = HEADING_SEPARATOR.join(h for h in self._headings if h)
        self.outline.append(path)

    def add_line(self, line: str) -> None:
        self._lines.append(line)

    def finish(self) -> list[Section]:
        self._flush()
        return self._sections

    def _flush(self) -> None:
        text = "\n".join(self._lines)
        self._lines = []
        if not has_text(text):
            return
        if not self._headings:
            self._sections.extend(part_sections(text, self._part_chars))
            return
        path = HEADING_SEPARATOR.join(h for h in self._headings if h)
        locator = f"section:{path}"
        count = self._seen_locators.get(locator, 0) + 1
        self._seen_locators[locator] = count
        if count > 1:  # the same heading path twice in one document
            path = f"{path} ({count})"
            locator = f"section:{path}"
        units = paragraphs(text) or [normalize_text(text)]
        self._sections.append(Section("section", None, locator, f"Section: {path}", units))
