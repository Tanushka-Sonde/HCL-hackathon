"""Conversation context management (FR-06).

Keeps only the last N turns per session (never unlimited history), detects
follow-up questions, and rewrites them into a standalone normalized query by
carrying over key terms from the most recent turn. The turns selected for a
request are recorded in its query event.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass

from src.knowledge.text import content_tokens

_FOLLOWUP_START = re.compile(
    r"^\s*(and|also|what about|how about|then|so|but|what if|same for|and for)\b", re.I
)
_PRONOUNS = re.compile(
    r"\b(it|its|that|this|they|them|those|these|there|one|ones)\b", re.I
)


@dataclass
class Turn:
    query_id: str
    query: str
    normalized: str
    answer: str
    route: str


class ConversationMemory:
    """Bounded per-session turn history (in-process)."""

    def __init__(self, max_turns: int = 3, max_sessions: int = 500) -> None:
        self._max_turns = max_turns
        self._max_sessions = max_sessions
        self._sessions: dict[str, deque[Turn]] = {}

    def history(self, session_id: str) -> list[Turn]:
        return list(self._sessions.get(session_id, ()))

    def add(self, session_id: str, turn: Turn) -> None:
        if (
            session_id not in self._sessions
            and len(self._sessions) >= self._max_sessions
        ):
            self._sessions.pop(next(iter(self._sessions)))
        self._sessions.setdefault(session_id, deque(maxlen=self._max_turns)).append(
            turn
        )


def is_followup(query: str, history: list[Turn]) -> bool:
    if not history:
        return False
    if _FOLLOWUP_START.search(query) or _PRONOUNS.search(query):
        return True
    return len(content_tokens(query)) <= 2


def resolve(query: str, history: list[Turn]) -> tuple[str, list[Turn]]:
    """Return (normalized_query, selected_turns)."""
    normalized = " ".join(query.split())
    if not is_followup(normalized, history):
        return normalized, []
    previous = history[-1]
    own = set(content_tokens(normalized))
    carried: list[str] = []
    for tok in content_tokens(previous.normalized):
        if tok not in own and tok not in carried and tok != "context":
            carried.append(tok)
    carried = carried[:8]
    if carried:
        normalized = f"{normalized} (context: {' '.join(carried)})"
    return normalized, [previous]
