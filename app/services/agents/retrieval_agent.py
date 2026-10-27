from __future__ import annotations

import uuid

from app.core.schemas import AgentStep, AnalysisMode, ObjectiveProfile, RouteDecision
from app.services.agents.contracts import AgentDecision, AgentToolCall


class RetrievalAgent:
    def plan(
        self,
        *,
        route_used: str,
        objective_profile: ObjectiveProfile,
        analysis_mode: AnalysisMode,
        requested_top_k: int,
        has_visual_request: bool,
        context: dict | None = None,
    ) -> tuple[dict, AgentStep]:
        context = context or {}
        document_memories = context.get("document_memories", [])
        strategy = "hybrid"
        top_k = requested_top_k
        use_multimodal = has_visual_request or route_used in {"visual_question", "chart_analysis", "table_analysis"}
        has_structured_docs = any((memory.get("metadata") or {}).get("table_count", 0) or (memory.get("metadata") or {}).get("chart_count", 0) for memory in document_memories)
        if objective_profile == "legal":
            top_k = max(top_k, 10 if analysis_mode != "quick" else 8)
            strategy = "hybrid_clause_aware"
        elif objective_profile == "research":
            top_k = max(top_k, 10)
            strategy = "hybrid_multihop"
        elif objective_profile == "enterprise":
            top_k = max(top_k, 8)
            strategy = "hybrid_policy_trace"
        if analysis_mode == "agentic":
            top_k = max(top_k, 12)
        if has_structured_docs and route_used in {"factual", "analytical", "multi_hop"}:
            top_k = max(top_k, 10)
        use_graph = objective_profile in {"legal", "research", "enterprise"} and analysis_mode == "agentic"
        plan = {
            "strategy": strategy,
            "top_k": top_k,
            "use_multimodal": use_multimodal,
            "use_graph": use_graph,
            "use_table_visual_boost": use_multimodal or has_structured_docs,
            "document_memory_count": len(document_memories),
        }
        tools = [
            AgentToolCall(tool_name="dense_search", arguments={"vector": "text_dense", "top_k": top_k}, reason="Semantic document recall."),
            AgentToolCall(tool_name="sparse_search", arguments={"vector": "text_sparse", "optional": True}, reason="Exact term recall when BGE-M3 sparse is enabled."),
        ]
        if use_graph:
            tools.append(AgentToolCall(tool_name="search_graph", arguments={"top_k": min(top_k, 12)}, reason="Entity and relationship recall with source-backed graph memory."))
        decision = AgentDecision(
            agent_name="RetrievalAgent",
            objective_profile=objective_profile,
            analysis_mode=analysis_mode,
            intent=route_used,
            confidence=0.82 if document_memories else 0.68,
            tools=tools,
            output_schema={"strategy": "string", "top_k": "integer", "use_multimodal": "boolean", "use_graph": "boolean"},
            notes=[f"strategy={strategy}", f"structured_docs={has_structured_docs}"],
        )
        plan["agent_decision"] = decision.model_dump()
        step = AgentStep(
            step_id=str(uuid.uuid4()),
            agent_name="RetrievalAgent",
            action="select_retrieval_strategy",
            output_summary=f"Using {strategy} with top_k={top_k}.",
            metadata={**plan, "route_used": route_used, "objective_profile": objective_profile, "analysis_mode": analysis_mode},
        )
        return plan, step

    def route_decision(
        self,
        *,
        route_used: str,
        objective_profile: ObjectiveProfile,
        analysis_mode: AnalysisMode,
        retrieval_plan: dict,
        reason: str,
    ) -> RouteDecision:
        return RouteDecision(
            route=route_used,
            objective_profile=objective_profile,
            analysis_mode=analysis_mode,
            use_multimodal=bool(retrieval_plan.get("use_multimodal")),
            use_graph=bool(retrieval_plan.get("use_graph")),
            requested_top_k=int(retrieval_plan.get("top_k", 5)),
            retrieval_strategy=str(retrieval_plan.get("strategy", "hybrid")),
            reason=reason,
        )
