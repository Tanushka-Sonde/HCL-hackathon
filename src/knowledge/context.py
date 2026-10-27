"""Conversation context management (FR-06).

Keeps only the last N turns per session (never unlimited history), detects
follow-up questions, and rewrites them into a standalone query. The turns
selected for a request and the rewrite are recorded in its query event.

A question is a follow-up only when it clearly depends on the previous turn:
it starts with a follow-up phrase ("and", "what about") or a pronoun ("it",
"those"), ends with a pronoun ("who approves it?"), or is very short
(two content words or fewer). "Is there a parental leave policy?" is a
new question, so nothing from earlier turns leaks into it.

Context is carried from the previous turn's *original* words, never its
rewritten form, so carried terms cannot snowball across turns. Routing uses
the user's own words; carried terms only help retrieval and generation.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.core.logging import get_logger
from src.knowledge.text import content_tokens

if TYPE_CHECKING:
    from src.core.config import Settings

logger = get_logger(__name__)

_FOLLOWUP_START = re.compile(
    r"^\s*(and|also|what about|how about|then|so|but|what if|same for|and for|"
    r"it|its|that|this|they|them|those|these)\b",
    re.I,
)
_TRAILING_PRONOUN = re.compile(
    r"\b(it|that|this|them|those|these|one)\s*[?.!]*\s*$", re.I
)
# Two, not three: "parental leave policy" (3 words) is a complete question.
_SHORT_QUESTION_WORDS = 2
_MAX_CARRIED = 8

REWRITE_PROMPT = (
    "Rewrite the user's follow-up question as one standalone question, using "
    "the previous question only to resolve what it refers to. Do not answer it. "
    "Output only the rewritten question."
)


@dataclass
class Turn:
    query_id: str
    query: str
    normalized: str
    answer: str
    route: str


@dataclass
class Resolution:
    normalized: str
    selected_turns: list[Turn] = field(default_factory=list)
    carried_terms: list[str] = field(default_factory=list)
    method: str = "none"  # none | rule | llm


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
    if _FOLLOWUP_START.search(query) or _TRAILING_PRONOUN.search(query):
        return True
    return len(content_tokens(query)) <= _SHORT_QUESTION_WORDS


def resolve(query: str, history: list[Turn]) -> Resolution:
    """Rule-based rewrite: append key terms from the previous question."""
    normalized = " ".join(query.split())
    if not is_followup(normalized, history):
        return Resolution(normalized)
    previous = history[-1]
    own = set(content_tokens(normalized))
    carried: list[str] = []
    for tok in content_tokens(previous.query):  # original words, not rewritten
        if tok not in own and tok not in carried:
            carried.append(tok)
    carried = carried[:_MAX_CARRIED]
    if carried:
        normalized = f"{normalized} (context: {' '.join(carried)})"
    return Resolution(normalized, [previous], carried, "rule")


async def rewrite_with_llm(
    query: str, previous: Turn, settings: Settings
) -> tuple[str | None, int, int]:
    """One short LLM call to make a follow-up standalone. (text, in, out tokens)."""
    from src.knowledge.generation import get_async_client

    try:
        completion = await get_async_client(settings).chat.completions.create(
            model=settings.groq_model_name,
            messages=[
                {"role": "system", "content": REWRITE_PROMPT},
                {
                    "role": "user",
                    "content": f"Previous question: {previous.query}\n"
                    f"Follow-up question: {query}",
                },
            ],
            temperature=0.0,
            max_tokens=80,
        )
    except Exception as exc:
        logger.warning("kis_context_rewrite_failed", error=str(exc)[:200])
        return None, 0, 0
    text = " ".join((completion.choices[0].message.content or "").split())
    usage = completion.usage
    tokens_in = getattr(usage, "prompt_tokens", 0) or 0
    tokens_out = getattr(usage, "completion_tokens", 0) or 0
    if not text or len(text) > 400:
        return None, tokens_in, tokens_out
    return text.strip('"'), tokens_in, tokens_out
