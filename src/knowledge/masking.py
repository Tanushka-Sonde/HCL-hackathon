"""Response masking of personal data and salaries for role = user (WP-4).

Masking happens only when a response is built for a ``user``. The database,
the index and the admin view keep the raw text, and citations and grounding
are validated on the raw answer first, so masking cannot change a score.
Person names are not masked (that would need named-entity recognition).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

_CURRENCY = r"(?:₹|INR|Rs\.?|USD|US\$|\$|EUR|€|GBP|£)"
_NUMBER = r"\d[\d,]*(?:\.\d+)?"
_AMOUNT_RE = re.compile(
    rf"{_CURRENCY}\s?{_NUMBER}(?:\s?(?:lakhs?|LPA|k|K|million|mn|per annum|/month))?"
    rf"|{_NUMBER}\s?(?:lakhs?|LPA|CTC|per annum|/month)\b",
    re.I,
)
_SALARY_WORD_RE = re.compile(
    r"\b(salary|salaries|ctc|compensation|pay|payout|wages?|bonus(?:es)?|"
    r"stipend|package|remuneration)\b",
    re.I,
)
_SALARY_WINDOW = 40

_ACCOUNT_RE = re.compile(
    r"(?P<pre>\b(?:account|a/c|acct|ifsc)\b[^\n]{0,30}?)(?<!\d)(?P<num>\d{9,18})(?!\d)"
    r"|(?<!\d)(?P<num2>\d{9,18})(?!\d)(?P<post>[^\n]{0,30}?\b(?:account|a/c|acct)\b)",
    re.I,
)

# Applied in order: longer, more specific patterns first.
_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "email",
        "[EMAIL]",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    ("pan", "[PAN]", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("card", "[CARD]", re.compile(r"\b(?:\d{4}[\s-]){3}\d{4}\b")),
    ("national_id", "[ID]", re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")),
    (
        "phone",
        "[PHONE]",
        re.compile(
            r"(?<![\w-])(?:\+?\d{1,3}[\s-])?\(?\d{3}\)?[\s-]\d{3}[\s-]\d{4}\b"
            r"|(?<!\d)(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"
        ),
    ),
]

_SENSITIVE_COLUMN_RE = re.compile(
    r"salary|ctc|compensation|pay|bonus|wage|stipend|email|phone|pan|account", re.I
)


def _mask_accounts(text: str, counts: Counter[str]) -> str:
    def sub(m: re.Match[str]) -> str:
        counts["account"] += 1
        if m.group("num"):
            return f"{m.group('pre')}[ACCOUNT]"
        return f"[ACCOUNT]{m.group('post')}"

    return _ACCOUNT_RE.sub(sub, text)


def _mask_salaries(text: str, counts: Counter[str]) -> str:
    keywords = [m.span() for m in _SALARY_WORD_RE.finditer(text)]
    if not keywords:
        return text
    spans = []
    for m in _AMOUNT_RE.finditer(text):
        start, end = m.span()
        if any(
            ks - _SALARY_WINDOW <= end and start <= ke + _SALARY_WINDOW
            for ks, ke in keywords
        ):
            spans.append((start, end))
    for start, end in reversed(spans):
        text = text[:start] + "[SALARY]" + text[end:]
    counts["salary"] += len(spans)
    return text


def mask_for_user(text: str | None) -> tuple[str, dict[str, int]]:
    """Return (masked_text, counts by type)."""
    if not text:
        return text or "", {}
    counts: Counter[str] = Counter()
    text = _mask_salaries(text, counts)
    text = _mask_accounts(text, counts)
    for name, token, rx in _PATTERNS:
        text, n = rx.subn(token, text)
        if n:
            counts[name] += n
    return text, {k: v for k, v in counts.items() if v}


def detect_pii(text: str | None) -> dict[str, int]:
    """Counts only (used for the trace's safety section)."""
    return mask_for_user(text)[1]


def mask_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Mask sensitive columns entirely and PII inside other string values."""
    counts: Counter[str] = Counter()
    out = []
    for row in rows:
        clean: dict[str, Any] = {}
        for key, value in row.items():
            if _SENSITIVE_COLUMN_RE.search(key) and value is not None:
                clean[key] = "[MASKED]"
                counts["column"] += 1
            elif isinstance(value, str):
                clean[key], found = mask_for_user(value)
                counts.update(found)
            else:
                clean[key] = value
        out.append(clean)
    return out, dict(counts)


def merge_counts(*parts: dict[str, int]) -> dict[str, int]:
    total: Counter[str] = Counter()
    for part in parts:
        total.update(part)
    return {k: v for k, v in total.items() if v}
