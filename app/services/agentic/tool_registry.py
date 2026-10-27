from __future__ import annotations

from app.services.agentic.state import AgentToolCall


class AgenticToolRegistry:
    SAFE_TOOL_PURPOSES = {
        "search_documents": "Find tenant-scoped document evidence.",
        "search_graph": "Find entity and relationship evidence linked to source pages.",
        "expand_query": "Rewrite or expand the user question for recall.",
        "rerank_evidence": "Prioritize retrieved evidence for answer grounding.",
        "extract_clauses": "Inspect legal clauses and obligations.",
        "extract_obligations": "Extract obligations, dates, owners, and risks.",
        "compare_documents": "Compare evidence across multiple documents.",
        "cluster_evidence": "Group related findings.",
        "detect_contradictions": "Flag contradictory evidence.",
        "verify_claims": "Verify final answer claims against citations.",
        "build_evidence_canvas": "Prepare source cards and citation evidence.",
        "synthesize_answer": "Generate the grounded final answer.",
    }

    def normalize(self, tools: list[str]) -> list[AgentToolCall]:
        calls: list[AgentToolCall] = []
        for tool in dict.fromkeys(tools):
            purpose = self.SAFE_TOOL_PURPOSES.get(tool)
            if purpose:
                calls.append(AgentToolCall(tool_name=tool, purpose=purpose))
        return calls
