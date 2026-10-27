from __future__ import annotations

import re


class QueryRewriter:
    """Deterministic multi-query expansion with offline-safe behavior."""

    FOLLOW_UP_TERMS = {"it", "this", "that", "they", "them", "those", "same"}

    def expand(
        self,
        question: str,
        *,
        interpreted_query: str | None = None,
        route_used: str = "factual",
        objective_profile: str = "general",
        max_queries: int = 4,
    ) -> list[str]:
        base = (interpreted_query or question).strip()
        if not base:
            return []
        queries = [base]
        lowered = base.lower()
        if route_used in {"multi_hop", "analytical", "comparison", "follow_up"}:
            queries.append(f"{base} key evidence source page")
        if objective_profile == "legal":
            queries.append(f"{base} clause obligation risk date party")
        elif objective_profile == "research":
            queries.append(f"{base} finding method assumption recommendation")
        elif objective_profile == "enterprise":
            queries.append(f"{base} policy control owner audit risk")
        if any(term in lowered.split() for term in self.FOLLOW_UP_TERMS):
            queries.append(re.sub(r"\b(it|this|that|they|them|those|same)\b", "the referenced item", base, flags=re.IGNORECASE))
        return list(dict.fromkeys(query for query in queries if query))[:max_queries]

