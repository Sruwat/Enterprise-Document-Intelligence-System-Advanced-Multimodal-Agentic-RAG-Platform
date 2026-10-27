from __future__ import annotations

import re

from app.core.schemas import RouteDecision


class RuleBasedRouter:
    MULTI_HOP_PATTERNS = (r"\bcompare\b", r"\brelationship\b", r"\bwhy\b", r"\bhow\b")
    SUMMARY_PATTERNS = (r"\bsummarize\b", r"\boverview\b", r"\bsummary\b")
    COMPARISON_PATTERNS = (r"\bcompare\b", r"\bdifference\b", r"\bversus\b", r"\bvs\b")

    def route(self, question: str) -> RouteDecision:
        text = question.lower().strip()
        if len(text) < 4:
            return RouteDecision(route="insufficient_context", requested_top_k=3, reason="Question is too short.")
        if any(re.search(pattern, text) for pattern in self.COMPARISON_PATTERNS):
            return RouteDecision(route="comparison", requested_top_k=8, reason="Comparison query benefits from broader context.")
        if any(re.search(pattern, text) for pattern in self.SUMMARY_PATTERNS):
            return RouteDecision(route="summary", requested_top_k=8, reason="Summary query requires more context chunks.")
        if any(re.search(pattern, text) for pattern in self.MULTI_HOP_PATTERNS):
            return RouteDecision(route="multi_hop", requested_top_k=10, use_graph=False, reason="Potential multi-step reasoning query.")
        return RouteDecision(route="factual", requested_top_k=5, reason="Direct factual query.")
