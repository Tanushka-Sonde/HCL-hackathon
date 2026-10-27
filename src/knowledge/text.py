"""Shared text utilities: tokenization, stemming, stopwords, sentence splitting."""

from __future__ import annotations

import re

# Tokens keep hyphenated identifiers intact (e.g. "acr-2291", "hr-pol-007")
# so exact IDs remain matchable by keyword retrieval.
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
# "[" is deliberately not a sentence start, so a trailing citation tag such as
# "... 7 years. [S1]" stays attached to the sentence it supports.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")

# fmt: off
STOPWORDS: frozenset[str] = frozenset(
    """
    a about above after again all also am an and any are as at be been before
    being below between both but by can could did do does doing down during
    each few for from further had has have having he her here hers him his how
    i if in into is it its itself just long many me more most much my no nor
    not now of off on once only or other our ours out over own please same she
    should so some such tell than that the their theirs them then there these
    they this those through to too under until up us very was we were what
    when where which while who whom why will with would you your yours
    s t d ll re ve m
    """.split()  # noqa: SIM905 - readable word list
)
# fmt: on

_SUFFIXES = ("ing", "ed", "es", "s")


def stem(token: str) -> str:
    """Light suffix stemmer: claims->claim, submitted->submit, trips->trip.

    Identifiers (tokens with digits or hyphens) are never stemmed.
    """
    if len(token) <= 4 or not token.isalpha():
        return token
    if token.endswith("ies"):
        return token[:-3] + "y"  # policies -> policy
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            base = token[: -len(suffix)]
            if suffix == "es" and not base.endswith(("s", "x", "z", "ch", "sh")):
                base = token[:-1]  # notes -> note (not "not")
            if suffix in ("ing", "ed") and len(base) > 3 and base[-1] == base[-2]:
                base = base[:-1]  # submitted -> submitt -> submit
            return base
    return token


def tokenize(text: str) -> list[str]:
    """Lowercase tokenization that keeps hyphenated IDs as one token.

    Hyphenated tokens also emit their parts, so "PRJ-1002" matches both
    "prj-1002" and "1002".
    """
    tokens: list[str] = []
    for tok in _TOKEN_RE.findall(text.lower()):
        tokens.append(tok)
        if "-" in tok or "_" in tok:
            tokens.extend(p for p in re.split(r"[-_]", tok) if p)
    return tokens


def keyword_tokens(text: str) -> list[str]:
    """Stemmed tokens (stopwords kept) for BM25 indexing."""
    return [stem(t) for t in tokenize(text)]


def content_tokens(text: str) -> list[str]:
    """Stemmed tokens with stopwords removed."""
    return [stem(t) for t in tokenize(text) if t not in STOPWORDS]


_LIST_ITEM_RE = re.compile(r"^([-*•]|\d+[.)]|\(\d+\))\s")


def _reflow(text: str) -> list[str]:
    """Join hard-wrapped lines (e.g. from PDF extraction) into logical lines.

    A line break is kept when the previous line ends a sentence/label, the
    next line is a list item, or there is a blank line between them.
    """
    logical: list[str] = []
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if current:
                logical.append(current)
            current = ""
            continue
        if (
            current
            and not current.endswith((".", "!", "?", ":"))
            and not _LIST_ITEM_RE.match(line)
        ):
            current = f"{current} {line}"
        else:
            if current:
                logical.append(current)
            current = line
    if current:
        logical.append(current)
    return logical


def split_sentences(text: str) -> list[str]:
    """Split text into sentences (simple regex heuristic)."""
    parts: list[str] = []
    for line in _reflow(text):
        parts.extend(s.strip() for s in _SENTENCE_RE.split(line) if s.strip())
    return parts


def numbers_in(text: str) -> set[str]:
    """Numeric literals in text, normalized (commas removed)."""
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}
