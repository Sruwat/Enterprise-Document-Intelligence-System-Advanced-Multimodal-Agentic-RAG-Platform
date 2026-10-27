from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.schemas import QueryRequest, UserRecord


@dataclass(frozen=True)
class AgentToolCall:
    tool_name: str
    purpose: str
    status: str = "planned"
    result_count: int = 0
    latency_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgenticPlan:
    run_mode: str
    route: str
    strategy: str
    tools: list[str]
    safety_policy: str
    confidence_policy: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_mode": self.run_mode,
            "route": self.route,
            "strategy": self.strategy,
            "tools": self.tools,
            "safety_policy": self.safety_policy,
            "confidence_policy": self.confidence_policy,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class VerificationResult:
    grounding_status: str
    confidence: float
    citation_count: int
    missing_evidence: list[str] = field(default_factory=list)
    unsupported_claim_risk: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "grounding_status": self.grounding_status,
            "confidence": self.confidence,
            "citation_count": self.citation_count,
            "missing_evidence": self.missing_evidence,
            "unsupported_claim_risk": self.unsupported_claim_risk,
        }


@dataclass(frozen=True)
class AgenticQueryServices:
    settings: Any
    agent_orchestrator: Any
    router_service: Any
    dense_retriever: Any
    hybrid_retriever: Any
    reranker: Any
    planner: Any
    multistep_engine: Any
    session_memory: Any
    primary_llm: Any
    fallback_llm: Any
    graph_repository: Any
    eval_logger: Any
    metadata_store: Any
    redis_service: Any
    query_cache: Any
    context_agent: Any
    retrieval_agent: Any
    evidence_agent: Any
    legal_agent: Any
    study_agent: Any
    enterprise_agent: Any
    synthesis_agent: Any


@dataclass(frozen=True)
class AgenticRunContext:
    request: QueryRequest
    user: UserRecord
    services: AgenticQueryServices
    streaming: bool = False
