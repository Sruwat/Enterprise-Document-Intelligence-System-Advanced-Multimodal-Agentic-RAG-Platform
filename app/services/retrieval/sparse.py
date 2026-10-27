from __future__ import annotations

import time

from app.core.logging import get_logger
from app.core.schemas import ChunkRecord

logger = get_logger(__name__)


class BM25Retriever:
    def __init__(self, sparse_store, metadata_store) -> None:
        self.sparse_store = sparse_store
        self.metadata_store = metadata_store

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
        needs_post_filter = bool(workspace_id or document_ids or tenant_id or objective_profile or content_type)
        results = self.sparse_store.search(question, top_k=top_k * 5 if needs_post_filter else top_k)
        chunk_ids = [chunk_id for chunk_id, _ in results]
        fetched = {chunk.chunk_id: chunk for chunk in self.metadata_store.get_chunks(chunk_ids, workspace_id=workspace_id, document_ids=document_ids)}
        chunks: list[ChunkRecord] = []
        for chunk_id, score in results:
            chunk = fetched.get(chunk_id)
            if not chunk:
                continue
            if tenant_id and str(chunk.metadata.get("tenant_id") or "") not in {"", tenant_id}:
                continue
            if objective_profile and str(chunk.metadata.get("objective_profile") or "general") not in {"general", objective_profile}:
                continue
            if content_type:
                allowed = {content_type} if isinstance(content_type, str) else set(content_type)
                actual = chunk.content_type or chunk.metadata.get("content_type", "text")
                if actual not in allowed:
                    continue
            chunk.sparse_score = score
            chunks.append(chunk)
            if len(chunks) >= top_k:
                break
        logger.info(
            "sparse_retrieval_completed question_length=%s top_k=%s result_count=%s latency_ms=%.2f",
            len(question.split()),
            top_k,
            len(chunks),
            (time.perf_counter() - start) * 1000,
        )
        return chunks
