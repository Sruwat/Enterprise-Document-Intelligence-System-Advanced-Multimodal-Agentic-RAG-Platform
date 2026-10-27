from __future__ import annotations


def should_abstain(
    confidence: float,
    min_confidence: float,
    chunks_available: int,
    *,
    coverage: float = 1.0,
    grounding_score: float = 1.0,
    citation_count: int = 0,
) -> bool:
    if chunks_available == 0:
        return True
    if citation_count == 0:
        return True
    if coverage < 0.4:
        return True
    if grounding_score < 0.35:
        return True
    return confidence < min_confidence
