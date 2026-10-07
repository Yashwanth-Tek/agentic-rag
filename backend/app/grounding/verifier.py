"""Sentence-level verification. Code, not the model, has the final say.

1. A second Claude call (schema-constrained JSON, no tools) labels every sentence against the
   passages it cites.
2. Code then enforces the rules: every sentence must be labelled, a "supported" sentence must
   carry a valid citation, and any unsupported sentence rejects the whole draft.
"""

import logging
from dataclasses import dataclass
from typing import Literal

import anthropic
from pydantic import BaseModel

from app.agent.prompts import VERIFIER_SYSTEM_PROMPT
from app.agent.run import EvidenceItem
from app.config import Settings
from app.grounding.sentences import Sentence
from app.llm import FALLBACK_BETA, to_app_error

log = logging.getLogger(__name__)

# extra_caveat: a remark that the documents hold nothing more about something the question did
# not ask. It is dropped like no_claim: never shown, and it does not make the answer partial.
Verdict = Literal["supported", "unsupported", "not_in_kb", "extra_caveat", "no_claim"]
MAX_VERIFIER_TOKENS = 8000


@dataclass(frozen=True)
class Assessment:
    status: Literal["answered", "partial", "not_found", "rejected"]
    sentences: list[tuple[Sentence, Verdict]]


class _SentenceVerdict(BaseModel):
    sentence: int
    verdict: Verdict
    reason: str


class Verification(BaseModel):
    verdicts: list[_SentenceVerdict]


def verify(
    client: anthropic.Anthropic,
    settings: Settings,
    question: str,
    sentences: list[Sentence],
    ledger: dict[str, EvidenceItem],
) -> list[Verdict] | None:
    """One verdict per sentence, or None when the verifier's output can't be used."""
    cited_sources = list(dict.fromkeys(s for sentence in sentences for s in sentence.sources))
    passage_ids = {source: f"P{i + 1}" for i, source in enumerate(cited_sources)}
    passages = "\n\n".join(
        f'<passage id="{passage_ids[source]}" source="{ledger[source].document_name}'
        f'{" — " + ledger[source].label if ledger[source].label else ""}">\n'
        f"{chr(10).join(ledger[source].units)}\n</passage>"
        for source in cited_sources
    )
    numbered = "\n".join(
        f"{n}. [cites: {', '.join(passage_ids[s] for s in sentence.sources) or 'nothing'}] "
        f"{sentence.text}"
        for n, sentence in enumerate(sentences, start=1)
    )
    prompt = (
        f"<question>\n{question}\n</question>\n\n"
        f"<passages>\n{passages or '(no passages cited)'}\n</passages>\n\n"
        f"<answer_sentences>\n{numbered}\n</answer_sentences>"
    )
    try:
        response = client.beta.messages.parse(
            model=settings.anthropic_model,
            max_tokens=MAX_VERIFIER_TOKENS,
            system=VERIFIER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_format=Verification,
            output_config={"effort": settings.anthropic_effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.APIError as exc:
        raise to_app_error(exc) from exc

    if response.stop_reason != "end_turn" or response.parsed_output is None:
        log.warning("verifier output unusable", extra={"stop_reason": response.stop_reason})
        return None
    by_number = {v.sentence: v.verdict for v in response.parsed_output.verdicts}
    if set(by_number) != set(range(1, len(sentences) + 1)):
        log.warning("verifier skipped or invented sentences", extra={"returned": len(by_number)})
        return None
    return [by_number[n] for n in range(1, len(sentences) + 1)]


def assess(sentences: list[Sentence], verdicts: list[Verdict] | None) -> Assessment:
    if verdicts is None or len(verdicts) != len(sentences):
        return Assessment("rejected", [])
    # A claim labelled supported but carrying no valid citation is treated as unsupported.
    checked: list[tuple[Sentence, Verdict]] = [
        (s, "unsupported" if v == "supported" and not s.citations else v)
        for s, v in zip(sentences, verdicts, strict=True)
    ]
    kinds = {verdict for _, verdict in checked}
    if "unsupported" in kinds:
        return Assessment("rejected", checked)
    if "supported" not in kinds:
        return Assessment("not_found", checked)
    return Assessment("partial" if "not_in_kb" in kinds else "answered", checked)
