from __future__ import annotations

import time

from app.core.logging import get_logger
from app.core.schemas import ChunkRecord

logger = get_logger(__name__)


class HybridRetriever:
    def __init__(self, dense_retriever, sparse_retriever, dense_weight: float = 0.7, sparse_weight: float = 0.3, rrf_k: int = 60) -> None:
        self.dense_retriever = dense_retriever
        self.sparse_retriever = sparse_retriever
        self.dense_weight = dense_weight
        self.sparse_weight = sparse_weight
        self.rrf_k = rrf_k
        self.metadata_store = dense_retriever.metadata_store

    def retrieve(
        self,
        question: str,
        top_k: int = 5,
        workspace_id: str | None = None,
        document_ids: list[str] | None = None,
        tenant_id: str | None = None,
        objective_profile: str | None = None,
        content_type: str | list[str] | None = None,
    ) -> list[ChunkRecord]:
        start = time.perf_counter()
        dense = self.dense_retriever.retrieve(
            question,
            top_k=top_k * 2,
            workspace_id=workspace_id,
            document_ids=document_ids,
            tenant_id=tenant_id,
            objective_profile=objective_profile,
            content_type=content_type,
        )
        sparse = self.sparse_retriever.retrieve(
            question,
            top_k=top_k * 2,
            workspace_id=workspace_id,
            document_ids=document_ids,
            tenant_id=tenant_id,
            objective_profile=objective_profile,
            content_type=content_type,
        )
        merged: dict[str, ChunkRecord] = {}

        for rank, chunk in enumerate(dense, start=1):
            chunk.combined_score = self.dense_weight * (1.0 / (self.rrf_k + rank))
            merged[chunk.chunk_id] = chunk

        for rank, chunk in enumerate(sparse, start=1):
            existing = merged.get(chunk.chunk_id)
            sparse_component = self.sparse_weight * (1.0 / (self.rrf_k + rank))
            if existing:
                existing.sparse_score = chunk.sparse_score
                existing.combined_score = (existing.combined_score or 0.0) + sparse_component
            else:
                chunk.combined_score = sparse_component
                merged[chunk.chunk_id] = chunk

        fused = sorted(merged.values(), key=lambda chunk: chunk.combined_score or 0.0, reverse=True)[:top_k]
        stitched = self._stitch_adjacent_chunks(fused, max_items=max(top_k + 2, top_k))
        logger.info(
            "hybrid_retrieval_completed top_k=%s dense_count=%s sparse_count=%s fused_count=%s stitched_count=%s latency_ms=%.2f",
            top_k,
            len(dense),
            len(sparse),
            len(fused),
            len(stitched),
            (time.perf_counter() - start) * 1000,
        )
        return stitched

    def _stitch_adjacent_chunks(self, chunks: list[ChunkRecord], max_items: int) -> list[ChunkRecord]:
        if not chunks:
            return []
        ordered: list[ChunkRecord] = []
        seen: set[str] = set()
        neighbor_ids: list[str] = []
        for chunk in chunks:
            if chunk.chunk_id not in seen:
                ordered.append(chunk)
                seen.add(chunk.chunk_id)
            for neighbor_id in (chunk.prev_chunk_id, chunk.next_chunk_id):
                if neighbor_id and neighbor_id not in seen:
                    neighbor_ids.append(neighbor_id)
        if neighbor_ids and len(ordered) < max_items:
            for neighbor in self.metadata_store.get_chunks(neighbor_ids, workspace_id=chunks[0].workspace_id):
                if neighbor.chunk_id in seen:
                    continue
                base_score = next(
                    (
                        parent.combined_score
                        for parent in chunks
                        if parent.prev_chunk_id == neighbor.chunk_id or parent.next_chunk_id == neighbor.chunk_id
                    ),
                    0.0,
                )
                neighbor.combined_score = (base_score or 0.0) * 0.92
                neighbor.metadata = {**neighbor.metadata, "stitched": True}
                ordered.append(neighbor)
                seen.add(neighbor.chunk_id)
                if len(ordered) >= max_items:
                    break
        return ordered
