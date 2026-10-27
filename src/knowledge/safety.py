"""Safety controls: prompt-injection detection, evidence sanitisation, PII redaction.

Retrieved content is treated as untrusted data. Sentences inside evidence
that look like instructions to the assistant are removed before the prompt
is built and recorded as safety events. A query that itself attempts to
override the assistant's rules is blocked with a controlled response.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.knowledge.text import split_sentences

INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "ignore_instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.]{0,40}\b(previous|prior|above|earlier|all|any|your|the)\b[^.]{0,20}\b(instructions?|rules?|prompts?|guidelines?)",
        re.I,
    ),
    "role_override": re.compile(
        r"\b(you are now|act as|pretend to be|from now on you)\b", re.I
    ),
    "prompt_exfiltration": re.compile(
        r"\b(reveal|print|show|output|leak)\b[^.]{0,30}\b(system prompt|hidden prompt|instructions|api key|password|secret)",
        re.I,
    ),
    "jailbreak": re.compile(
        r"\b(jailbreak|do anything now|DAN mode|developer mode)\b", re.I
    ),
    "new_rule": re.compile(r"\bnew (rule|instruction|directive)s?\s*:", re.I),
    "persistent_override": re.compile(
        r"\bfrom now on\b[^.]{0,60}\b(answer|respond|reply|say|output|ignore)\b"
        r"|\b(answer|respond|reply|say|output)\b[^.]{0,60}\bfrom now on\b",
        re.I,
    ),
    "role_tag": re.compile(
        r"(?:^|\n)\s*(system|developer)\s*:|<\|?(system|im_start)\|?>", re.I
    ),
    "imperative_to_ai": re.compile(r"\byou must now\b", re.I),
    "directive_to_ai": re.compile(
        r"\b(AI|assistant|language model|LLM|chatbot)s?\b[^.]{0,30}\b(must|should|shall) (now )?(respond|reply|say|answer|output)",
        re.I,
    ),
}

_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(
        r"(?<![\w-])(?:\+?\d{1,3}[\s-])?\(?\d{3}\)?[\s-]\d{3}[\s-]\d{4}\b"
    ),
    "national_id": re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b"),
    "card_number": re.compile(r"\b(?:\d{4}[\s-]){3}\d{4}\b"),
}

BLOCKED_QUERY_ANSWER = (
    "I can't follow instructions that try to change my rules or reveal hidden "
    "configuration. Please ask a question about the indexed documents or business data."
)


def detect_injection(text: str) -> list[str]:
    """Return the names of injection patterns found in the text."""
    return [name for name, rx in INJECTION_PATTERNS.items() if rx.search(text)]


@dataclass
class SanitizedText:
    text: str
    removed: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)


def sanitize_evidence(text: str) -> SanitizedText:
    """Drop instruction-like sentences from retrieved evidence."""
    kept: list[str] = []
    removed: list[str] = []
    patterns: set[str] = set()
    for sentence in split_sentences(text):
        hits = detect_injection(sentence)
        if hits:
            removed.append(sentence)
            patterns.update(hits)
        else:
            kept.append(sentence)
    if not removed:
        return SanitizedText(text=text)
    kept.append("[Removed: embedded instruction detected in source document]")
    return SanitizedText(
        text=" ".join(kept), removed=removed, patterns=sorted(patterns)
    )


def redact_pii(text: str) -> tuple[str, dict[str, int]]:
    """Mask PII patterns in model output; returns (text, counts by type)."""
    counts: dict[str, int] = {}
    for name, rx in _PII_PATTERNS.items():
        text, n = rx.subn(f"[REDACTED {name.upper()}]", text)
        if n:
            counts[name] = n
    return text, counts
