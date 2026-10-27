from __future__ import annotations

from app.core.schemas import Citation, ChunkRecord, EvidenceItem, VisualEvidenceCard


def build_citations(chunks: list[ChunkRecord], max_items: int = 5) -> list[Citation]:
    citations: list[Citation] = []
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        snippet = chunk.text[:240].strip()
        page_assets = chunk.metadata.get("multimodal_assets", {}) if chunk.metadata else {}
        anchors = page_assets.get("source_anchors", []) or page_assets.get("visual_assets", [])
        anchor = anchors[0] if anchors else {}
        citations.append(
            Citation(
                document_id=chunk.document_id,
                filename=chunk.filename,
                page_number=chunk.page_number,
                chunk_id=chunk.chunk_id,
                snippet=snippet,
                anchor_id=anchor.get("anchor_id"),
                content_type=chunk.metadata.get("content_type", "text") if chunk.metadata else "text",
                preview_path=anchor.get("preview_path") or page_assets.get("preview_path"),
                bbox=anchor.get("bbox"),
            )
        )
        if len(citations) >= max_items:
            break
    return citations


def build_evidence(
    chunks: list[ChunkRecord],
    include_visual: bool = True,
    evidence_kind: str | None = None,
) -> tuple[list[EvidenceItem], list[VisualEvidenceCard]]:
    evidence: list[EvidenceItem] = []
    visual_cards: list[VisualEvidenceCard] = []
    for citation in build_citations(chunks):
        evidence.append(
            EvidenceItem(
                evidence_id=citation.chunk_id,
                document_id=citation.document_id,
                filename=citation.filename,
                page_number=citation.page_number,
                content_type=citation.content_type,
                snippet=citation.snippet,
                anchor_id=citation.anchor_id,
                preview_path=citation.preview_path,
                bbox=citation.bbox,
            )
        )
    if not include_visual:
        return evidence, visual_cards
    for chunk in chunks:
        page_assets = chunk.metadata.get("multimodal_assets", {}) if chunk.metadata else {}
        for asset in page_assets.get("visual_assets", []):
            evidence_id = asset.get("anchor_id") or chunk.chunk_id
            visual_type = asset.get("visual_type", asset.get("content_type", "visual"))
            if visual_type == "page":
                continue
            if evidence_kind in {"chart", "table"}:
                visual_type = evidence_kind
            interpretation = chunk.text[:240].strip()
            visual_cards.append(
                VisualEvidenceCard(
                    evidence_id=evidence_id,
                    document_id=chunk.document_id,
                    filename=chunk.filename,
                    page_number=chunk.page_number,
                    visual_type=visual_type,
                    preview_path=asset.get("preview_path") or page_assets.get("preview_path"),
                    bbox=asset.get("bbox"),
                    title=f"{visual_type.replace('_', ' ').title()} evidence",
                    interpretation=interpretation,
                    plain_language_explanation=f"This visual is evidence from page {chunk.page_number}; verify the highlighted page before relying on numeric details.",
                )
            )
    unique_cards = {card.evidence_id: card for card in visual_cards}
    return evidence, list(unique_cards.values())
