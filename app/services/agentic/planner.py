from __future__ import annotations

from app.services.agentic.state import AgenticPlan


class AgenticPlanner:
    def build_plan(
        self,
        *,
        route_used: str,
        objective_profile: str,
        analysis_mode: str,
        retrieval_strategy: str,
        tools: list[str],
        graph_enabled: bool,
    ) -> AgenticPlan:
        run_mode = "agentic" if analysis_mode in {"agentic", "deep"} else "single_pass_guarded"
        safety_policy = "grounded_only_with_verified_citations"
        confidence_policy = "abstain_when_evidence_or_confidence_is_insufficient"
        strategy_parts = [retrieval_strategy or "hybrid"]
        if graph_enabled:
            strategy_parts.append("graph_enriched")
        if route_used in {"comparison", "multi_hop", "analytical"}:
            strategy_parts.append("multi_step")
        return AgenticPlan(
            run_mode=run_mode,
            route=route_used,
            strategy="+".join(strategy_parts),
            tools=list(dict.fromkeys(tools)),
            safety_policy=safety_policy,
            confidence_policy=confidence_policy,
            metadata={
                "objective_profile": objective_profile,
                "analysis_mode": analysis_mode,
                "graph_enabled": graph_enabled,
            },
        )
