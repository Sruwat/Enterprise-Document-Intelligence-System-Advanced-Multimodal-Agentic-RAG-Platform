from __future__ import annotations

import re

from app.core.schemas import IntentLabel, QueryPlanStep
from app.services.memory.session_memory import SessionMemory


class QueryPlanner:
    COMPARISON_SPLITTERS = (r"\bvs\.?\b", r"\bversus\b", r"\bcompare\b", r"\bdifference between\b")
    ANALYTICAL_CUES = {"why", "impact", "analyze", "analysis", "driver", "drivers", "trend", "risks"}
    MULTI_HOP_CUES = {"relationship", "cause", "because", "before", "after", "depend", "depends"}

    def __init__(self, memory: SessionMemory | None = None) -> None:
        self.memory = memory

    def plan(self, question: str, intent: IntentLabel, session_id: str | None = None) -> list[QueryPlanStep]:
        text = question.strip()
        if not text:
            return [QueryPlanStep(step=1, query=question, type="retrieve")]

        if intent == "follow_up":
            return self._plan_follow_up(text, session_id)
        if intent == "comparison":
            return self._plan_comparison(text)
        if intent in {"multi_hop", "analytical", "scenario", "quiz"}:
            return self._plan_reasoning(text, intent)
        if intent in {"summary", "visual_question", "table_analysis", "chart_analysis", "translation"}:
            return [QueryPlanStep(step=1, query=text, type="retrieve")]
        return [QueryPlanStep(step=1, query=text, type="retrieve")]

    def _plan_follow_up(self, question: str, session_id: str | None) -> list[QueryPlanStep]:
        if not self.memory or not session_id:
            return [QueryPlanStep(step=1, query=question, type="retrieve")]
        entities = self.memory.get_recent_entities(session_id, limit=2)
        if not entities:
            return [QueryPlanStep(step=1, query=question, type="retrieve")]
        expanded = f"{question} about {' and '.join(entities)}"
        return [QueryPlanStep(step=1, query=expanded, type="retrieve", notes="Expanded with recent memory entities.")]

    def _plan_comparison(self, question: str) -> list[QueryPlanStep]:
        subjects = self._extract_comparison_subjects(question)
        if len(subjects) < 2:
            return [QueryPlanStep(step=1, query=question, type="retrieve")]
        focus = self._extract_focus(question)
        steps = [
            QueryPlanStep(step=1, query=f"{subjects[0]} {focus}".strip(), type="retrieve", notes=f"Gather evidence for {subjects[0]}."),
            QueryPlanStep(step=2, query=f"{subjects[1]} {focus}".strip(), type="retrieve", notes=f"Gather evidence for {subjects[1]}."),
            QueryPlanStep(step=3, type="synthesis", depends_on=[1, 2], notes="Compare the retrieved evidence."),
        ]
        return steps

    def _plan_reasoning(self, question: str, intent: IntentLabel) -> list[QueryPlanStep]:
        clauses = self._split_reasoning_clauses(question)
        if len(clauses) <= 1:
            return [
                QueryPlanStep(step=1, query=question, type="retrieve"),
                QueryPlanStep(step=2, type="synthesis", depends_on=[1], notes=f"Synthesize findings for {intent}."),
            ]
        capped = clauses[:2]
        steps = [QueryPlanStep(step=index, query=clause, type="retrieve") for index, clause in enumerate(capped, start=1)]
        steps.append(QueryPlanStep(step=len(steps) + 1, type="synthesis", depends_on=[step.step for step in steps], notes="Combine supporting evidence across steps."))
        return steps

    def _extract_comparison_subjects(self, question: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", question.strip(" ?"))
        working = re.sub(r"^(compare|what is the difference between)\s+", "", normalized, flags=re.IGNORECASE)
        for splitter in self.COMPARISON_SPLITTERS:
            parts = [part.strip(" ,") for part in re.split(splitter, working, flags=re.IGNORECASE) if part.strip(" ,")]
            if len(parts) >= 2:
                return [self._trim_subject(part) for part in parts[:2]]
        return []

    def _extract_focus(self, question: str) -> str:
        match = re.search(r"\b(in terms of|for|regarding|on)\b(.+)$", question, flags=re.IGNORECASE)
        if match:
            return match.group(2).strip(" ?")
        return ""

    def _trim_subject(self, text: str) -> str:
        cleaned = re.sub(r"\b(in terms of|for|regarding|on)\b.*$", "", text, flags=re.IGNORECASE).strip(" ?")
        return cleaned

    def _split_reasoning_clauses(self, question: str) -> list[str]:
        parts = re.split(r"\b(?:and|then|after|because|while)\b", question, flags=re.IGNORECASE)
        clauses = [part.strip(" ,?") for part in parts if len(part.strip(" ,?")) >= 8]
        if len(clauses) >= 2:
            return clauses
        return [question.strip()]
