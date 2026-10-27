from __future__ import annotations

import uuid

from app.core.schemas import AgentStep, ObjectiveProfile
from app.services.agents.contracts import AgentDecision, AgentToolCall


class SynthesisAgent:
    def build_preferences(
        self,
        *,
        language: str,
        explanation_level: str,
        answer_mode: str,
        intent: str,
        objective_profile: ObjectiveProfile,
        analysis_mode: str,
        context: dict,
        objective_note: str,
    ) -> tuple[dict, AgentStep]:
        preferences = {
            "language": language,
            "explanation_level": explanation_level,
            "answer_mode": answer_mode,
            "intent": intent,
            "objective_profile": objective_profile,
            "analysis_mode": analysis_mode,
            "user_goal": context.get("user_goal"),
            "recent_entities": context.get("recent_entities", []),
            "objective_note": objective_note,
            "document_memories": context.get("document_memories", []),
            "json_contract": {
                "answer": "grounded natural language answer",
                "citations_required": True,
                "missing_evidence": "list of claims that could not be grounded",
                "suggested_followups": "list of next grounded questions",
            },
        }
        decision = AgentDecision(
            agent_name="SynthesisAgent",
            objective_profile=objective_profile,
            analysis_mode=analysis_mode,
            intent=intent,
            confidence=0.9,
            tools=[AgentToolCall(tool_name="grounded_generation", arguments={"require_citations": True}, reason="Answer only from selected context.")],
            output_schema=preferences["json_contract"],
            notes=[objective_note] if objective_note else [],
        )
        preferences["agent_decision"] = decision.model_dump()
        step = AgentStep(
            step_id=str(uuid.uuid4()),
            agent_name="SynthesisAgent",
            action="prepare_grounded_generation",
            output_summary=f"Prepared {objective_profile}/{analysis_mode} generation preferences.",
            metadata={key: value for key, value in preferences.items() if key != "recent_entities"},
        )
        return preferences, step
