from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.schemas import QueryRequest

QueryExecutionMode = Literal["fast", "balanced", "deep"]


@dataclass(frozen=True)
class QueryModePolicy:
    mode: QueryExecutionMode
    candidate_pool: int
    rerank_k: int
    context_k: int
    use_reranker: bool
    use_graph: bool
    use_multistep: bool
    reranker_required: bool


class QueryModeResolver:
    COMPLEX_MARKERS = {
        "compare",
        "comparison",
        "conflict",
        "across",
        "contracts",
        "obligations",
        "risks",
        "audit",
        "compliance",
        "multi",
        "multiple",
    }

    def resolve(self, request: QueryRequest, settings) -> QueryModePolicy:
        mode = request.query_mode
        if mode == "auto":
            mode = self._auto_mode(request.question)
        if mode == "fast":
            return QueryModePolicy(
                mode="fast",
                candidate_pool=max(1, settings.fast_retrieval_k),
                rerank_k=0,
                context_k=max(1, settings.fast_context_k),
                use_reranker=False,
                use_graph=False,
                use_multistep=False,
                reranker_required=False,
            )
        if mode == "deep":
            return QueryModePolicy(
                mode="deep",
                candidate_pool=max(1, settings.deep_retrieval_k),
                rerank_k=max(1, min(settings.deep_rerank_k, settings.rerank_max_candidates)),
                context_k=max(1, settings.deep_context_k),
                use_reranker=bool(settings.enable_reranker if request.use_reranker is None else request.use_reranker),
                use_graph=True,
                use_multistep=request.mode == "multistep" or request.analysis_mode in {"deep", "agentic"},
                reranker_required=bool(settings.reranker_required),
            )
        return QueryModePolicy(
            mode="balanced",
            candidate_pool=max(1, settings.balanced_retrieval_k),
            rerank_k=max(1, min(settings.balanced_rerank_k, settings.rerank_max_candidates)),
            context_k=max(1, settings.balanced_context_k),
            use_reranker=bool(settings.enable_reranker if request.use_reranker is None else request.use_reranker),
            use_graph=True,
            use_multistep=False,
            reranker_required=False,
        )

    def _auto_mode(self, question: str) -> QueryExecutionMode:
        lowered = question.lower()
        if len(lowered.split()) > 22 or any(marker in lowered for marker in self.COMPLEX_MARKERS):
            return "deep"
        return "balanced"
