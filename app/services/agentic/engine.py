from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.core.schemas import AgentStep, Citation, QueryRequest, QueryResponse, UserRecord
from app.services.agentic.planner import AgenticPlanner
from app.services.agentic.state import AgenticQueryServices
from app.services.agentic.tool_registry import AgenticToolRegistry
from app.services.agentic.verification import AgenticVerifier


class AgenticQueryEngine:
    """Audit-safe agentic contract layered behind the existing query route."""

    def __init__(self) -> None:
        self.planner = AgenticPlanner()
        self.tools = AgenticToolRegistry()
        self.verifier = AgenticVerifier()

    def run(
        self,
        *,
        request: QueryRequest,
        services: AgenticQueryServices,
        user: UserRecord,
    ) -> QueryResponse:
        from app.services.agentic.runtime import _query_documents_runtime

        return _query_documents_runtime(
            request,
            settings=services.settings,
            agent_orchestrator=services.agent_orchestrator,
            router_service=services.router_service,
            dense_retriever=services.dense_retriever,
            hybrid_retriever=services.hybrid_retriever,
            reranker=services.reranker,
            planner=services.planner,
            multistep_engine=services.multistep_engine,
            session_memory=services.session_memory,
            primary_llm=services.primary_llm,
            fallback_llm=services.fallback_llm,
            graph_repository=services.graph_repository,
            eval_logger=services.eval_logger,
            metadata_store=services.metadata_store,
            redis_service=services.redis_service,
            query_cache=services.query_cache,
            context_agent=services.context_agent,
            retrieval_agent=services.retrieval_agent,
            evidence_agent=services.evidence_agent,
            legal_agent=services.legal_agent,
            study_agent=services.study_agent,
            enterprise_agent=services.enterprise_agent,
            synthesis_agent=services.synthesis_agent,
            agentic_engine=self,
            user=user,
        )

    def stream(
        self,
        *,
        request: QueryRequest,
        services: AgenticQueryServices,
        user: UserRecord,
    ) -> Iterable[str]:
        from app.services.agentic.runtime import _stream_query_native

        return _stream_query_native(
            request=request,
            settings=services.settings,
            router_service=services.router_service,
            dense_retriever=services.dense_retriever,
            hybrid_retriever=services.hybrid_retriever,
            reranker=services.reranker,
            session_memory=services.session_memory,
            primary_llm=services.primary_llm,
            fallback_llm=services.fallback_llm,
            graph_repository=services.graph_repository,
            eval_logger=services.eval_logger,
            metadata_store=services.metadata_store,
            redis_service=services.redis_service,
            query_cache=services.query_cache,
            context_agent=services.context_agent,
            retrieval_agent=services.retrieval_agent,
            evidence_agent=services.evidence_agent,
            legal_agent=services.legal_agent,
            study_agent=services.study_agent,
            enterprise_agent=services.enterprise_agent,
            synthesis_agent=services.synthesis_agent,
            agent_orchestrator=services.agent_orchestrator,
            agentic_engine=self,
            user=user,
        )

    def build_contract(
        self,
        *,
        route_used: str,
        objective_profile: str,
        analysis_mode: str,
        retrieval_strategy: str,
        pipeline: list[dict[str, Any]],
        graph_enabled: bool,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], AgentStep]:
        tool_names = [tool for stage in pipeline for tool in stage.get("tools", [])]
        plan = self.planner.build_plan(
            route_used=route_used,
            objective_profile=objective_profile,
            analysis_mode=analysis_mode,
            retrieval_strategy=retrieval_strategy,
            tools=tool_names,
            graph_enabled=graph_enabled,
        )
        tool_trace = [call.__dict__ for call in self.tools.normalize(plan.tools)]
        step = AgentStep(
            step_id="agentic-contract",
            agent_name="AgenticQueryEngine",
            action="prepare_agentic_contract",
            status="completed",
            output_summary="Prepared audit-safe plan, tool trace, and grounding policy.",
            metadata={"agent_plan": plan.to_dict(), "tool_trace": tool_trace},
        )
        return plan.to_dict(), tool_trace, step

    def verify_answer(
        self,
        *,
        answer: str,
        citations: list[Citation],
        confidence: float,
        final_context_size: int,
    ) -> dict[str, Any]:
        return self.verifier.verify(
            answer=answer,
            citations=citations,
            confidence=confidence,
            final_context_size=final_context_size,
        ).to_dict()
