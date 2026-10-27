from __future__ import annotations

from typing import Protocol

from app.core.schemas import ChunkRecord


class Retriever(Protocol):
    def retrieve(self, question: str, top_k: int) -> list[ChunkRecord]:
        ...
