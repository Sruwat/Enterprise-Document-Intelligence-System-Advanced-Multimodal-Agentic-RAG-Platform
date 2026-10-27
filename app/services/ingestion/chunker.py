from __future__ import annotations

import re
import uuid

from app.core.schemas import ChunkRecord


class RecursiveChunker:
    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 120) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_document(self, document_id: str, filename: str, pages: list[dict], workspace_id: str = "default") -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        position = 0
        for page in pages:
            text = self._normalize_text(page["text"])
            if not text:
                continue
            page_metadata = page.get("metadata", {})
            content_type = self._content_type(page_metadata)
            for clause in page_metadata.get("clauses", []) or []:
                clause_text = self._normalize_text(f"{clause.get('title', 'Clause')}: {clause.get('text', '')}")
                if not clause_text:
                    continue
                clause_metadata = {
                    **page_metadata,
                    "content_type": "clause",
                    "clause": clause,
                    "bbox": clause.get("bbox") or page_metadata.get("bbox"),
                    "risk_tags": clause.get("risk_tags", []),
                    "source_anchors": [
                        anchor
                        for anchor in page_metadata.get("source_anchors", [])
                        if anchor.get("anchor_id") == clause.get("artifact_id")
                    ]
                    or page_metadata.get("source_anchors", []),
                }
                chunks.append(
                    ChunkRecord(
                        chunk_id=str(uuid.uuid4()),
                        document_id=document_id,
                        workspace_id=workspace_id,
                        filename=filename,
                        page_number=page["page_number"],
                        text=clause_text[: self.chunk_size * 2],
                        section=clause.get("title") or page.get("section"),
                        token_count=len(clause_text.split()),
                        chunk_position=position,
                        content_type="clause",
                        bbox=clause_metadata.get("bbox"),
                        section_path=[*(page_metadata.get("section_path", []) or []), clause.get("title") or "Clause"],
                        risk_tags=clause.get("risk_tags", []),
                        metadata={
                            "page_number": page["page_number"],
                            "section_title": clause.get("title") or page.get("section"),
                            "chunk_position": position,
                            "page_metadata": clause_metadata,
                            "multimodal_assets": clause_metadata,
                            "content_type": "clause",
                            "bbox": clause_metadata.get("bbox"),
                            "section_path": [*(page_metadata.get("section_path", []) or []), clause.get("title") or "Clause"],
                            "risk_tags": clause.get("risk_tags", []),
                            "legal_metadata": page_metadata.get("legal_metadata", {}),
                        },
                    )
                )
                position += 1
            start = 0
            while start < len(text):
                end = min(start + self.chunk_size, len(text))
                if end < len(text):
                    sentence_break = text.rfind(" ", start, end)
                    if sentence_break > start + int(self.chunk_size * 0.6):
                        end = sentence_break
                chunk_text = text[start:end].strip()
                if chunk_text:
                    chunks.append(
                        ChunkRecord(
                            chunk_id=str(uuid.uuid4()),
                            document_id=document_id,
                            workspace_id=workspace_id,
                            filename=filename,
                            page_number=page["page_number"],
                            text=chunk_text,
                            section=page.get("section"),
                            token_count=len(chunk_text.split()),
                            chunk_position=position,
                            content_type=content_type,
                            bbox=page_metadata.get("bbox"),
                            section_path=page_metadata.get("section_path", []),
                            visual_caption=page_metadata.get("visual_caption"),
                            table_json=page_metadata.get("table_json"),
                            chart_series=page_metadata.get("chart_series"),
                            risk_tags=page_metadata.get("risk_tags", []),
                            metadata={
                                "page_number": page["page_number"],
                                "section_title": page.get("section"),
                                "chunk_position": position,
                                "page_metadata": page_metadata,
                                "multimodal_assets": page_metadata,
                                "content_type": content_type,
                                "bbox": page_metadata.get("bbox"),
                                "section_path": page_metadata.get("section_path", []),
                                "visual_caption": page_metadata.get("visual_caption"),
                                "table_json": page_metadata.get("table_json"),
                                "chart_series": page_metadata.get("chart_series"),
                                "risk_tags": page_metadata.get("risk_tags", []),
                                "legal_metadata": page_metadata.get("legal_metadata", {}),
                                "ocr_confidence": page_metadata.get("ocr_confidence"),
                                "is_scanned": page_metadata.get("is_scanned", False),
                            },
                        )
                    )
                    position += 1
                if end >= len(text):
                    break
                start = max(end - self.chunk_overlap, 0)
        for index, chunk in enumerate(chunks):
            chunk.prev_chunk_id = chunks[index - 1].chunk_id if index > 0 else None
            chunk.next_chunk_id = chunks[index + 1].chunk_id if index < len(chunks) - 1 else None
            chunk.metadata["prev_chunk_id"] = chunk.prev_chunk_id
            chunk.metadata["next_chunk_id"] = chunk.next_chunk_id
        return chunks

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _content_type(metadata: dict) -> str:
        if metadata.get("chart_series"):
            return "chart"
        if metadata.get("table_json") or metadata.get("tables"):
            return "table"
        if metadata.get("has_images"):
            return "visual_text"
        return "text"
