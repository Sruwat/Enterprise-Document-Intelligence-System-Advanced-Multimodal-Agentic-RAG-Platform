from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.core.schemas import AgentRun, AgentStep, Citation, QueryRequest, QueryResponse, UserRecord


class AgentOrchestrator:
    """Phase 6 durable state-machine boundary for query orchestration.

    The existing deterministic agents still do the domain work. This service
    owns run lifecycle metadata, durable trace finalization, and Redis scratch
    state so the route can stay as a thin API adapter while the workflow moves
    behind an explicit orchestrator contract.
    """

    TOOL_ALLOWLIST = {
        "search_documents",
        "search_graph",
        "get_chat_context",
        "get_document_memory",
        "extract_entities",
        "extract_clauses",
        "extract_obligations",
        "compare_documents",
        "get_evidence",
        "verify_claims",
        "build_evidence_canvas",
        "synthesize_answer",
        "dense_search",
        "sparse_search",
        "grounded_generation",
        "clause_extractor",
        "obligation_timeline",
        "concept_map",
        "quiz_generator",
        "policy_trace",
        "compliance_evidence",
        "expand_query",
        "rerank_evidence",
        "cluster_evidence",
        "detect_contradictions",
    }

    def plan_pipeline(
        self,
        *,
        request: QueryRequest,
        route_used: str,
        retrieval_plan: dict[str, Any],
        needs_graph: bool = False,
    ) -> tuple[list[dict[str, Any]], AgentStep]:
        """Build the production query pipeline contract used by the route.

        The route still performs the heavy retrieval/generation work, but this
        method makes the orchestration explicit and traceable: planner,
        retrieval, optional graph/tool execution, verification, and synthesis.
        """
        tools = self.select_tools(
            objective_profile=request.objective_profile,
            analysis_mode=request.analysis_mode,
            route_used=route_used,
            needs_graph=needs_graph or bool(retrieval_plan.get("use_graph")),
        )
        pipeline = [
            {"stage": "planner", "status": "planned", "tools": ["expand_query"] if request.analysis_mode == "deep" else []},
            {"stage": "retriever", "status": "planned", "tools": ["search_documents"]},
            {"stage": "tool_executor", "status": "planned", "tools": tools},
            {"stage": "verifier", "status": "planned", "tools": ["verify_claims"]},
            {"stage": "synthesis", "status": "planned", "tools": ["synthesize_answer"]},
        ]
        step = AgentStep(
            step_id=str(uuid.uuid4()),
            agent_name="PlannerAgent",
            action="build_query_pipeline",
            status="completed",
            input_summary=f"route={route_used}; objective={request.objective_profile}; analysis={request.analysis_mode}",
            output_summary="Planned retrieval, tool execution, verification, and synthesis pipeline.",
            metadata={
                "pipeline": pipeline,
                "retrieval_strategy": retrieval_plan.get("strategy"),
                "top_k": retrieval_plan.get("top_k"),
                "tool_allowlist": sorted(self.TOOL_ALLOWLIST),
            },
        )
        return pipeline, step

    def select_tools(self, *, objective_profile: str, analysis_mode: str, route_used: str, needs_graph: bool = False) -> list[str]:
        tools = ["search_documents", "rerank_evidence", "build_evidence_canvas"]
        if needs_graph or objective_profile in {"legal", "research", "enterprise"} and analysis_mode in {"agentic", "deep"}:
            tools.append("search_graph")
        if objective_profile == "legal":
            tools.extend(["extract_clauses", "extract_obligations"])
        if objective_profile == "research" or analysis_mode == "deep":
            tools.extend(["expand_query", "cluster_evidence", "detect_contradictions"])
        if route_used in {"comparison", "multi_hop", "analytical"}:
            tools.append("compare_documents")
        tools.extend(["verify_claims", "synthesize_answer"])
        return [tool for tool in dict.fromkeys(tools) if tool in self.TOOL_ALLOWLIST]

    def retry_queries(self, question: str, *, route_used: str, objective_profile: str, response_language: str | None = None) -> list[str]:
        variants = [question]
        lowered = question.lower()
        if objective_profile == "legal" and not any(term in lowered for term in ("clause", "obligation", "party", "notice", "law")):
            variants.append(f"{question} clause obligation party notice governing law")
        if objective_profile == "research" or route_used in {"analytical", "multi_hop"}:
            variants.append(f"{question} evidence findings risks assumptions recommendation")
        if response_language in {"hindi", "hinglish"}:
            variants.append(f"{question} explain in English evidence terms")
        return list(dict.fromkeys(variant.strip() for variant in variants if variant.strip()))[:3]

    def graph_trace_step(self, graph_facts: list[Any]) -> AgentStep:
        return AgentStep(
            step_id=str(uuid.uuid4()),
            agent_name="ToolExecutor",
            action="search_graph",
            status="completed",
            output_summary=f"Retrieved {len(graph_facts)} graph fact(s).",
            metadata={
                "tool_calls": [{"tool_name": "search_graph", "status": "completed", "result_count": len(graph_facts)}],
                "facts": [self._graph_fact_payload(fact) for fact in graph_facts[:12]],
            },
        )

    def verification_step(
        self,
        *,
        answer: str,
        confidence: float,
        citations: list[Citation],
        final_context_size: int,
        route_used: str,
        objective_profile: str,
        min_confidence: float,
    ) -> tuple[bool, float, AgentStep]:
        missing_citations = not citations
        unsupported = self._has_unsupported_answer(answer, citations)
        legal_needs_support = objective_profile == "legal" and (missing_citations or unsupported)
        weak_confidence = confidence < min_confidence
        force_abstain = bool(missing_citations or weak_confidence or legal_needs_support or final_context_size == 0)
        verified_confidence = 0.0 if missing_citations or final_context_size == 0 else confidence
        status = "failed" if force_abstain else "completed"
        reasons = []
        if missing_citations:
            reasons.append("missing_citations")
        if weak_confidence:
            reasons.append("low_confidence")
        if unsupported:
            reasons.append("unsupported_claim_risk")
        if final_context_size == 0:
            reasons.append("no_evidence")
        step = AgentStep(
            step_id=str(uuid.uuid4()),
            agent_name="VerifierAgent",
            action="verify_answer_grounding",
            status=status,
            input_summary=f"route={route_used}; objective={objective_profile}; confidence={confidence}",
            output_summary="Answer passed grounding checks." if not force_abstain else f"Answer blocked: {', '.join(reasons)}.",
            metadata={
                "force_abstain": force_abstain,
                "reasons": reasons,
                "citation_count": len(citations),
                "final_context_size": final_context_size,
                "verified_confidence": verified_confidence,
                "tool_calls": [{"tool_name": "verify_claims", "status": status}],
            },
        )
        return force_abstain, verified_confidence, step

    def start_run(self, request: QueryRequest, user: UserRecord, redis_service=None) -> str:
        run_id = str(uuid.uuid4())
        self._set_state(
            redis_service,
            run_id,
            {
                "status": "running",
                "workspace_id": request.workspace_id,
                "session_id": request.session_id,
                "user_id": user.user_id,
                "objective_profile": request.objective_profile,
                "analysis_mode": request.analysis_mode,
                "started_at": datetime.utcnow().isoformat(),
            },
        )
        return run_id

    def finalize_response(
        self,
        *,
        orchestration_run_id: str,
        request: QueryRequest,
        response: QueryResponse,
        user: UserRecord,
        metadata_store,
        redis_service=None,
    ) -> QueryResponse:
        agent_run = response.agent_run or AgentRun(
            run_id=orchestration_run_id,
            session_id=request.session_id or "default",
            workspace_id=request.workspace_id,
            objective_profile=request.objective_profile,
            analysis_mode=request.analysis_mode,
            steps=[],
            created_at=datetime.utcnow(),
            metadata={},
        )
        agent_run.metadata = {
            **agent_run.metadata,
            "orchestration_run_id": orchestration_run_id,
            "orchestrator": "AgentOrchestrator",
            "user_id": user.user_id,
            "tool_allowlist": sorted(self.TOOL_ALLOWLIST),
            "final_status": "completed",
        }
        agent_run.steps = [*agent_run.steps, self._orchestrator_step(response)]
        response.agent_run = agent_run
        if response.evidence_canvas is not None:
            response.evidence_canvas.agent_steps = agent_run.steps
        metadata_store.log_agent_run(agent_run)
        self._set_state(
            redis_service,
            orchestration_run_id,
            {
                "status": "completed",
                "agent_run_id": agent_run.run_id,
                "workspace_id": request.workspace_id,
                "session_id": agent_run.session_id,
                "step_count": len(agent_run.steps),
                "confidence": response.confidence,
                "abstained": response.abstained,
                "completed_at": datetime.utcnow().isoformat(),
            },
        )
        return response

    def fail_run(self, *, orchestration_run_id: str, request: QueryRequest, error: Exception, redis_service=None) -> None:
        self._set_state(
            redis_service,
            orchestration_run_id,
            {
                "status": "failed",
                "workspace_id": request.workspace_id,
                "session_id": request.session_id,
                "error": str(error),
                "completed_at": datetime.utcnow().isoformat(),
            },
        )

    @staticmethod
    def _orchestrator_step(response: QueryResponse) -> AgentStep:
        tools: list[str] = []
        if response.retrieval_metadata.get("retrieval_strategy"):
            tools.extend(["search_documents"])
        if response.retrieval_metadata.get("retrieval_strategy", "").find("graph") >= 0:
            tools.append("search_graph")
        if response.evidence_canvas is not None:
            tools.append("build_evidence_canvas")
        tools.append("synthesize_answer")
        return AgentStep(
            step_id=str(uuid.uuid4()),
            agent_name="AgentOrchestrator",
            action="finalize_state_machine_run",
            status="completed",
            output_summary=f"Finalized durable run with {len(response.agent_run.steps if response.agent_run else [])} agent step(s).",
            metadata={
                "route_used": response.route_used,
                "tool_calls": [{"tool_name": tool, "status": "completed"} for tool in dict.fromkeys(tools)],
                "final_context_size": response.final_context_size,
                "needs_clarification": response.needs_clarification,
            },
        )

    @staticmethod
    def _set_state(redis_service, run_id: str, payload: dict[str, Any]) -> None:
        if redis_service is None:
            return
        set_agent_state = getattr(redis_service, "set_agent_state", None)
        if callable(set_agent_state):
            set_agent_state(run_id, payload)

    @staticmethod
    def _has_unsupported_answer(answer: str, citations: list[Citation]) -> bool:
        if not answer:
            return True
        lowered = answer.lower()
        if "do not have enough grounded evidence" in lowered:
            return False
        if not citations:
            return True
        risky_phrases = ("guarantee", "definitely", "legally binding advice", "you must sue", "will win")
        return any(phrase in lowered for phrase in risky_phrases)

    @staticmethod
    def _graph_fact_payload(fact: Any) -> dict[str, Any]:
        source = getattr(fact, "source", None)
        target = getattr(fact, "target", None)
        relationship = getattr(fact, "relationship", None)
        return {
            "source": getattr(source, "canonical_name", None),
            "source_type": getattr(source, "entity_type", None),
            "target": getattr(target, "canonical_name", None),
            "target_type": getattr(target, "entity_type", None),
            "relationship": getattr(relationship, "relationship_type", None),
            "document_id": getattr(fact, "document_id", None),
            "page_number": getattr(fact, "page_number", None),
            "evidence_anchor_id": getattr(fact, "evidence_anchor_id", None),
        }
