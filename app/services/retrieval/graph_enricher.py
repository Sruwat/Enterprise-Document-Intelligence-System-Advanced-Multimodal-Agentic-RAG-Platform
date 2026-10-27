from __future__ import annotations

from typing import Any

from app.core.schemas import ChunkRecord


class GraphEvidenceEnricher:
    def facts_to_chunks(self, facts: list[Any], *, workspace_id: str, limit: int) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        for index, fact in enumerate(facts[:limit]):
            document_id = getattr(fact, "document_id", None)
            page_number = getattr(fact, "page_number", None)
            if not document_id or not page_number:
                continue
            source = getattr(fact, "source", None)
            target = getattr(fact, "target", None)
            relationship = getattr(fact, "relationship", None)
            source_name = getattr(source, "canonical_name", "Entity")
            target_name = getattr(target, "canonical_name", None)
            relationship_type = getattr(relationship, "relationship_type", "REFERENCES")
            fact_text = f"Graph memory: {source_name}"
            if target_name:
                fact_text += f" {relationship_type} {target_name}"
            fact_text += "."
            chunk = ChunkRecord(
                chunk_id=f"graph-{getattr(fact, 'evidence_anchor_id', None) or document_id}-{page_number}-{index}",
                document_id=document_id,
                workspace_id=getattr(source, "workspace_id", workspace_id),
                filename=f"Graph memory for {document_id}",
                page_number=int(page_number),
                text=fact_text,
                token_count=len(fact_text.split()),
                content_type="text",
                metadata={
                    "content_type": "graph_fact",
                    "graph_score": 0.99,
                    "graph_fact": {
                        "source": source_name,
                        "source_type": getattr(source, "entity_type", None),
                        "target": target_name,
                        "target_type": getattr(target, "entity_type", None),
                        "relationship": relationship_type,
                        "evidence_anchor_id": getattr(fact, "evidence_anchor_id", None),
                    },
                },
                combined_score=0.99,
            )
            chunks.append(chunk)
        return chunks

