from __future__ import annotations

import time

from app.core.logging import get_logger
from app.core.schemas import ChunkRecord

logger = get_logger(__name__)


class DenseRetriever:
    def __init__(self, vector_store, embedder, metadata_store, default_top_k: int = 5) -> None:
        self.vector_store = vector_store
        self.embedder = embedder
        self.metadata_store = metadata_store
        self.default_top_k = default_top_k

    def retrieve(
        self,
        question: str,
        top_k: int | None = None,
        workspace_id: str | None = None,
        document_ids: list[str] | None = None,
        tenant_id: str | None = None,
        objective_profile: str | None = None,
        content_type: str | list[str] | None = None,
    ) -> list[ChunkRecord]:
        start = time.perf_counter()
        vector = self.embedder.embed_query(question)
        requested_top_k = top_k or self.default_top_k
        qdrant_filters = self._qdrant_filters(workspace_id=workspace_id, document_ids=document_ids, tenant_id=tenant_id, objective_profile=objective_profile, content_type=content_type)
        results = self.vector_store.query(
            vector,
            limit=requested_top_k * 3 if workspace_id or document_ids else requested_top_k,
            filters=qdrant_filters,
        )
        sparse_query = getattr(self.embedder, "embed_sparse_query", None)
        if callable(sparse_query):
            sparse_results = self.vector_store.query_sparse(sparse_query(question), limit=requested_top_k, filters=qdrant_filters)
            results = self._merge_results(results, sparse_results)
        chunk_ids = [str(result["id"]) for result in results]
        fetched = {chunk.chunk_id: chunk for chunk in self.metadata_store.get_chunks(chunk_ids, workspace_id=workspace_id, document_ids=document_ids)}
        chunks: list[ChunkRecord] = []
        for result in results:
            chunk = fetched.get(str(result["id"]))
            if chunk:
                chunk.dense_score = float(result["score"])
                chunks.append(chunk)
                if len(chunks) >= requested_top_k:
                    break
        logger.info(
            "dense_retrieval_completed question_length=%s top_k=%s result_count=%s latency_ms=%.2f",
            len(question.split()),
            requested_top_k,
            len(chunks),
            (time.perf_counter() - start) * 1000,
        )
        return chunks

    @staticmethod
    def _qdrant_filters(
        workspace_id: str | None = None,
        document_ids: list[str] | None = None,
        tenant_id: str | None = None,
        objective_profile: str | None = None,
        content_type: str | list[str] | None = None,
    ) -> dict:
        filters = {}
        if tenant_id:
            filters["tenant_id"] = tenant_id
        if workspace_id:
            filters["workspace_id"] = workspace_id
        if document_ids:
            filters["document_id"] = document_ids
        if objective_profile and objective_profile != "general":
            filters["objective_profile"] = objective_profile
        if content_type:
            filters["content_type"] = content_type
        return filters

    @staticmethod
    def _merge_results(dense_results: list[dict], sparse_results: list[dict]) -> list[dict]:
        if not sparse_results:
            return dense_results
        merged: dict[str, dict] = {}
        for rank, result in enumerate(dense_results, start=1):
            item = dict(result)
            item["score"] = float(item.get("score", 0.0)) + 1.0 / (60 + rank)
            merged[str(item["id"])] = item
        for rank, result in enumerate(sparse_results, start=1):
            key = str(result["id"])
            sparse_score = 1.0 / (60 + rank)
            if key in merged:
                merged[key]["score"] = float(merged[key].get("score", 0.0)) + sparse_score
            else:
                item = dict(result)
                item["score"] = sparse_score
                merged[key] = item
        return sorted(merged.values(), key=lambda item: float(item.get("score", 0.0)), reverse=True)
