from __future__ import annotations

from app.core.schemas import ChunkRecord


def compute_confidence(chunks: list[ChunkRecord], citation_count: int) -> float:
    if not chunks:
        return 0.0
    score_sum = 0.0
    for chunk in chunks:
        signal = max(chunk.rerank_score or 0.0, chunk.combined_score or 0.0, chunk.dense_score or 0.0)
        score_sum += max(signal, 0.0)
    avg_signal = score_sum / len(chunks)
    citation_bonus = min(citation_count / max(len(chunks), 1), 1.0) * 0.2
    normalized = min(avg_signal, 1.0)
    return round(min(normalized + citation_bonus, 1.0), 4)
