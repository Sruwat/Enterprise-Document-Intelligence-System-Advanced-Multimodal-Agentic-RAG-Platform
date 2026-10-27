from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field


@dataclass
class MemoryTurn:
    question: str
    answer: str
    entities: list[str] = field(default_factory=list)


class SessionMemory:
    FOLLOW_UP_PATTERNS = (
        r"^\s*(what about|how about|and\b|also\b|it\b|they\b|them\b|those\b|that\b|this\b)",
        r"\b(previous|earlier|above|former|latter)\b",
    )

    def __init__(self, max_turns: int = 6, redis_service=None) -> None:
        self.max_turns = max_turns
        self.redis_service = redis_service
        self._sessions: dict[str, deque[MemoryTurn]] = {}

    def add_turn(self, session_id: str, question: str, answer: str) -> None:
        if not session_id:
            return
        if self.redis_service is not None:
            self.redis_service.append_json(
                f"context:{session_id}:window",
                {"question": question, "answer": answer, "entities": self.extract_entities(f"{question} {answer}")},
                max_items=self.max_turns,
                ttl_seconds=60 * 60 * 24,
            )
        turns = self._sessions.setdefault(session_id, deque(maxlen=self.max_turns))
        turns.append(MemoryTurn(question=question, answer=answer, entities=self.extract_entities(f"{question} {answer}")))

    def get_recent_turns(self, session_id: str) -> list[MemoryTurn]:
        if not session_id:
            return []
        if self.redis_service is not None:
            payload = self.redis_service.get_json(f"context:{session_id}:window") or []
            if isinstance(payload, list) and payload:
                return [
                    MemoryTurn(
                        question=str(item.get("question", "")),
                        answer=str(item.get("answer", "")),
                        entities=list(item.get("entities", [])),
                    )
                    for item in payload[-self.max_turns :]
                    if isinstance(item, dict)
                ]
        return list(self._sessions.get(session_id, ()))

    def extract_entities(self, text: str) -> list[str]:
        tokens = re.findall(r"\b[A-Z][a-zA-Z0-9&.-]+(?:\s+[A-Z][a-zA-Z0-9&.-]+)*\b", text)
        seen: set[str] = set()
        entities: list[str] = []
        for token in tokens:
            normalized = token.strip()
            if len(normalized) < 3:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            entities.append(normalized)
        return entities

    def get_recent_entities(self, session_id: str, limit: int = 8) -> list[str]:
        entities: list[str] = []
        seen: set[str] = set()
        for turn in reversed(self.get_recent_turns(session_id)):
            for entity in turn.entities:
                lowered = entity.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                entities.append(entity)
                if len(entities) >= limit:
                    return entities
        return entities

    def is_follow_up(self, session_id: str, question: str) -> bool:
        if not self.get_recent_turns(session_id):
            return False
        text = question.strip()
        if not text:
            return False
        lowered = text.lower()
        if any(re.search(pattern, lowered) for pattern in self.FOLLOW_UP_PATTERNS):
            return True
        if len(lowered.split()) <= 6 and any(pronoun in lowered.split() for pronoun in {"it", "they", "them", "that", "this", "those"}):
            return True
        return False

    def build_memory_context(self, session_id: str) -> str:
        turns = self.get_recent_turns(session_id)
        if not turns:
            return ""
        lines: list[str] = []
        for index, turn in enumerate(turns[-3:], start=1):
            lines.append(f"Turn {index} question: {turn.question}")
            lines.append(f"Turn {index} answer: {turn.answer}")
        entities = self.get_recent_entities(session_id, limit=6)
        if entities:
            lines.append(f"Recent entities: {', '.join(entities)}")
        return "\n".join(lines)
