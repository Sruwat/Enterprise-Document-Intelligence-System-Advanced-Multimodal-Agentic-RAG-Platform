from __future__ import annotations

from typing import Protocol

from app.core.schemas import ChunkRecord


class Reranker(Protocol):
    def rerank(self, question: str, chunks: list[ChunkRecord], top_n: int) -> list[ChunkRecord]:
        ...
