from app.core.schemas import ChunkRecord
from app.services.guardrails.abstain import should_abstain
from app.services.guardrails.citation import build_citations
from app.services.guardrails.confidence import compute_confidence
from app.api.routes.query import _grounding_score


def test_citations_and_confidence():
    chunks = [
        ChunkRecord(
            chunk_id="c1",
            document_id="d1",
            filename="a.pdf",
            page_number=2,
            text="Revenue increased by 20 percent year over year.",
            rerank_score=0.9,
        )
    ]
    citations = build_citations(chunks)
    confidence = compute_confidence(chunks, len(citations))
    assert citations[0].page_number == 2
    assert confidence > 0.5
    assert should_abstain(confidence, 0.4, len(chunks), coverage=1.0, grounding_score=1.0, citation_count=len(citations)) is False


def test_abstains_on_low_grounding():
    chunks = [
        ChunkRecord(
            chunk_id="c1",
            document_id="d1",
            filename="a.pdf",
            page_number=2,
            text="Revenue increased by 20 percent year over year.",
            rerank_score=0.9,
        )
    ]
    citations = build_citations(chunks)
    confidence = compute_confidence(chunks, len(citations))
    grounding = _grounding_score("The company expanded blockchain hiring in Europe.", "What happened to hiring?", chunks)
    assert grounding < 0.35
    assert should_abstain(confidence, 0.4, len(chunks), coverage=1.0, grounding_score=grounding, citation_count=len(citations)) is True
