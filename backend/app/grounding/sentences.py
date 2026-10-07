"""Splits a draft into sentences (in code) and links each to the citations that overlap it."""

import re
from dataclasses import dataclass

from app.grounding.citations import Citation

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])[ \t]+|\n+")


@dataclass(frozen=True)
class Sentence:
    text: str
    citations: list[Citation]  # every citation overlapping this sentence, in draft order
    paragraph_start: bool  # preceded by a line break in the draft

    @property
    def sources(self) -> list[str]:
        """Distinct evidence sources cited in this sentence, in order of first citation."""
        return list(dict.fromkeys(c.evidence.source for c in self.citations))


def split_sentences(text: str, citations: list[Citation]) -> list[Sentence]:
    sentences: list[Sentence] = []
    position = 0
    after_break = True
    breaks = [*_SENTENCE_BREAK.finditer(text), None]
    for match in breaks:
        end = match.start() if match else len(text)
        raw = text[position:end]
        stripped = raw.strip()
        if any(ch.isalnum() for ch in stripped):
            start = position + len(raw) - len(raw.lstrip())
            stop = start + len(stripped)
            cited = [c for c in citations if c.start < stop and c.end > start]
            sentences.append(Sentence(stripped, cited, after_break))
        if match:
            after_break = "\n" in match.group(0)
            position = match.end()
    return sentences
