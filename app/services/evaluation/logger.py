from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from app.core.schemas import QueryResponse, RetrievalTrace


@dataclass
class QueryLogPayload:
    query_id: str
    question: str
    answer: str
    abstained: bool
    confidence: float
    route_used: str
    intent: str
    step_count: int
    citations: list[dict[str, Any]]
    retrieved_candidates: list[dict[str, Any]]
    reranked_candidates: list[dict[str, Any]]
    final_contexts: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    final_context_size: int
    latency_ms: dict[str, float]
    provider: str | None
    model: str | None
    session_id: str | None
    input_language: str | None
    response_language: str | None
    grounding_status: str | None
    verification: dict[str, Any]
    agent_plan: dict[str, Any]
    tool_trace: list[dict[str, Any]]
    created_at: str


class EvaluationLogger:
    def __init__(self, metadata_store) -> None:
        self.metadata_store = metadata_store

    def log_query(self, question: str, response: QueryResponse, trace: RetrievalTrace) -> str:
        query_id = str(uuid.uuid4())
        payload = QueryLogPayload(
            query_id=query_id,
            question=question,
            answer=response.answer,
            abstained=response.abstained,
            confidence=response.confidence,
            route_used=response.route_used,
            intent=trace.intent or response.intent,
            step_count=trace.step_count,
            citations=[citation.model_dump() for citation in response.citations],
            retrieved_candidates=[self._analytics_chunk(chunk) for chunk in trace.retrieved_candidates],
            reranked_candidates=[self._analytics_chunk(chunk) for chunk in trace.reranked_candidates],
            final_contexts=[self._analytics_chunk(chunk) for chunk in trace.final_contexts],
            steps=[step.model_dump() for step in trace.steps],
            final_context_size=trace.final_context_size,
            latency_ms=response.latency_ms,
            provider=trace.provider,
            model=trace.model,
            session_id=trace.session_id,
            input_language=response.retrieval_metadata.get("input_language"),
            response_language=response.answer_language,
            grounding_status=response.grounding_status,
            verification=response.verification,
            agent_plan=response.agent_plan,
            tool_trace=response.tool_trace,
            created_at=datetime.utcnow().isoformat(),
        )
        self.metadata_store.log_query(query_id, asdict(payload))
        return query_id

    @staticmethod
    def _analytics_chunk(chunk) -> dict[str, Any]:
        payload = chunk.model_dump()
        payload["text"] = chunk.text[:160]
        return payload
