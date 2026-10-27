from __future__ import annotations

import re
from typing import Any

from app.core.schemas import IntentDetectionResult, RouteDecision
from app.services.agents.contracts import StructuredRoutePlan
from app.services.llm.prompts import build_json_mode_prompt
from app.services.memory.session_memory import SessionMemory


class HybridIntentClassifier:
    SUMMARY_KEYWORDS = {"summarize", "summary", "overview", "brief", "recap"}
    COMPARISON_KEYWORDS = {"compare", "difference", "versus", "vs"}
    ANALYTICAL_KEYWORDS = {"analyze", "analysis", "trend", "impact", "risk", "reason", "drivers"}
    MULTI_HOP_KEYWORDS = {"relationship", "connect", "linked", "because", "before", "after", "across"}
    VISUAL_KEYWORDS = {"image", "figure", "visual", "diagram", "photo", "picture", "shown"}
    TABLE_KEYWORDS = {"table", "row", "column", "tabular"}
    CHART_KEYWORDS = {"chart", "graph", "plot", "axis", "trendline"}
    SCENARIO_KEYWORDS = {"scenario", "example", "suppose", "imagine", "real-life", "real life"}
    QUIZ_KEYWORDS = {"quiz", "test", "questions", "practice"}
    TRANSLATION_KEYWORDS = {"translate", "hinglish", "hindi"}
    FACTUAL_PREFIXES = {"what", "when", "where", "who", "which", "how many"}

    def __init__(self, llm_provider: Any | None = None, memory: SessionMemory | None = None) -> None:
        self.llm_provider = llm_provider
        self.memory = memory

    def classify(self, question: str, session_id: str | None = None) -> IntentDetectionResult:
        text = question.strip()
        lowered = text.lower()
        if len(lowered) < 4:
            return IntentDetectionResult(intent="unclear", confidence=0.95, reason="Question is too short.", signals={"length": len(lowered)})

        signals = self._build_signals(text, lowered, session_id)
        heuristic = self._heuristic_classification(lowered, signals)
        if self._should_refine_with_llm(heuristic):
            refined = self._refine_with_llm_json(question, heuristic, signals) or self._refine_with_llm(question, heuristic, signals)
            if refined:
                return refined
        return heuristic

    def route(self, question: str, session_id: str | None = None) -> RouteDecision:
        result = self.classify(question, session_id=session_id)
        top_k = self._requested_top_k(result.intent)
        return RouteDecision(route=result.intent, requested_top_k=top_k, reason=result.reason)

    def _build_signals(self, text: str, lowered: str, session_id: str | None) -> dict[str, Any]:
        tokens = re.findall(r"\w+", lowered)
        entities = re.findall(r"\b[A-Z][a-zA-Z0-9&.-]+(?:\s+[A-Z][a-zA-Z0-9&.-]+)*\b", text)
        keywords = set(tokens)
        signals = {
            "length": len(tokens),
            "has_summary_keyword": bool(keywords & self.SUMMARY_KEYWORDS),
            "has_comparison_keyword": bool(keywords & self.COMPARISON_KEYWORDS),
            "has_analytical_keyword": bool(keywords & self.ANALYTICAL_KEYWORDS),
            "has_multihop_keyword": bool(keywords & self.MULTI_HOP_KEYWORDS),
            "has_visual_keyword": bool(keywords & self.VISUAL_KEYWORDS),
            "has_table_keyword": bool(keywords & self.TABLE_KEYWORDS),
            "has_chart_keyword": bool(keywords & self.CHART_KEYWORDS),
            "has_scenario_keyword": bool(keywords & self.SCENARIO_KEYWORDS),
            "has_quiz_keyword": bool(keywords & self.QUIZ_KEYWORDS),
            "has_translation_keyword": bool(keywords & self.TRANSLATION_KEYWORDS),
            "entity_count": len(entities),
            "question_mark": "?" in text,
            "follow_up": self.memory.is_follow_up(session_id, text) if self.memory and session_id else False,
        }
        return signals

    def _heuristic_classification(self, lowered: str, signals: dict[str, Any]) -> IntentDetectionResult:
        reason = "Direct factual query."
        intent = "factual"
        confidence = 0.72

        if signals["follow_up"]:
            intent, reason, confidence = "follow_up", "Query depends on recent conversational context.", 0.88
        elif signals["has_chart_keyword"]:
            intent, reason, confidence = "chart_analysis", "Chart or graph evidence requested.", 0.9
        elif signals["has_table_keyword"]:
            intent, reason, confidence = "table_analysis", "Table evidence requested.", 0.9
        elif signals["has_visual_keyword"]:
            intent, reason, confidence = "visual_question", "Visual evidence requested.", 0.86
        elif signals["has_scenario_keyword"]:
            intent, reason, confidence = "scenario", "Scenario-style explanation requested.", 0.86
        elif signals["has_quiz_keyword"]:
            intent, reason, confidence = "quiz", "Practice-question mode requested.", 0.9
        elif signals["has_translation_keyword"]:
            intent, reason, confidence = "translation", "Language transformation requested.", 0.84
        elif (
            signals["has_summary_keyword"]
            or re.search(r"\b(what'?s|what is|tell me)\b.*\b(pdf|document|report|file)\b.*\babout\b", lowered)
            or re.search(r"\b(main|major|key)\b.*\b(outcomes?|findings?|points?|results?)\b", lowered)
        ):
            intent, reason, confidence = "summary", "Summary keywords detected.", 0.9
        elif signals["has_comparison_keyword"] or ("compare" in lowered or " vs " in lowered):
            intent, reason, confidence = "comparison", "Comparison cues detected.", 0.9
        elif signals["has_analytical_keyword"] or lowered.startswith("why ") or lowered.startswith("analyze "):
            intent, reason, confidence = "analytical", "Analytical reasoning cues detected.", 0.84
        elif signals["has_multihop_keyword"] or (" and " in lowered and signals["entity_count"] >= 2):
            intent, reason, confidence = "multi_hop", "Multiple related concepts suggest multi-hop retrieval.", 0.8
        elif signals["length"] <= 2:
            intent, reason, confidence = "unclear", "Question lacks enough detail.", 0.8
        elif any(lowered.startswith(prefix) for prefix in self.FACTUAL_PREFIXES):
            intent, reason, confidence = "factual", "Direct factual pattern detected.", 0.82

        return IntentDetectionResult(intent=intent, confidence=confidence, signals=signals, reason=reason)

    def _should_refine_with_llm(self, result: IntentDetectionResult) -> bool:
        provider_name = getattr(self.llm_provider, "provider_name", "")
        return bool(self.llm_provider and provider_name and provider_name != "grounded_fallback")

    def _refine_with_llm(
        self,
        question: str,
        heuristic: IntentDetectionResult,
        signals: dict[str, Any],
    ) -> IntentDetectionResult | None:
        choices = "factual, summary, visual_question, table_analysis, chart_analysis, comparison, scenario, quiz, translation, multi_hop, analytical, follow_up, unclear"
        prompt = (
            f"Intent classification task. Choose exactly one label from: {choices}. "
            f"Return only the label.\nQuestion: {question}\nSignals: {signals}\nHeuristic: {heuristic.intent}"
        )
        try:
            raw = self.llm_provider.generate(prompt, contexts=[], require_citations=False).strip().lower()
        except Exception:
            return None
        for label in ("factual", "summary", "visual_question", "table_analysis", "chart_analysis", "comparison", "scenario", "quiz", "translation", "multi_hop", "analytical", "follow_up", "unclear"):
            if raw == label:
                return IntentDetectionResult(
                    intent=label,
                    confidence=max(heuristic.confidence, 0.78),
                    signals=signals,
                    used_llm_refinement=True,
                    reason=f"LLM refinement selected {label}.",
                )
        return None

    def _refine_with_llm_json(
        self,
        question: str,
        heuristic: IntentDetectionResult,
        signals: dict[str, Any],
    ) -> IntentDetectionResult | None:
        schema_hint = {
            "intent": "one of factual, summary, visual_question, table_analysis, chart_analysis, comparison, scenario, quiz, translation, multi_hop, analytical, follow_up, unclear",
            "confidence": "number 0..1",
            "reason": "short explanation",
            "retrieval_strategy": "hybrid|dense|sparse|visual|table",
            "requested_top_k": "integer",
            "needs_clarification": "boolean",
        }
        messages = build_json_mode_prompt(
            "Classify document-query intent and retrieval strategy.",
            schema_hint,
            {"question": question, "signals": signals, "heuristic": heuristic.model_dump()},
        )
        prompt = "\n\n".join(message["content"] for message in messages)
        try:
            if hasattr(self.llm_provider, "generate_structured"):
                plan = self.llm_provider.generate_structured(prompt, StructuredRoutePlan)
            else:
                raw = self.llm_provider.generate(prompt, contexts=[], require_citations=False).strip()
                from app.services.llm.structured import validate_structured_output

                plan = validate_structured_output(raw, StructuredRoutePlan)
        except Exception as exc:
            failed_steps = getattr(self.llm_provider, "structured_trace_steps", None)
            if failed_steps:
                signals["structured_route_error"] = failed_steps[-1].model_dump(mode="json")
            else:
                signals["structured_route_error"] = str(exc)
            return None
        allowed = {
            "factual",
            "summary",
            "visual_question",
            "table_analysis",
            "chart_analysis",
            "comparison",
            "scenario",
            "quiz",
            "translation",
            "multi_hop",
            "analytical",
            "follow_up",
            "unclear",
        }
        if plan.intent not in allowed:
            return None
        return IntentDetectionResult(
            intent=plan.intent,  # type: ignore[arg-type]
            confidence=max(float(plan.confidence), heuristic.confidence),
            signals={**signals, "structured_route_plan": plan.model_dump()},
            used_llm_refinement=True,
            reason=plan.reason or f"Structured LLM route selected {plan.intent}.",
        )

    def _requested_top_k(self, intent: str) -> int:
        if intent in {"summary", "comparison", "table_analysis", "chart_analysis", "visual_question"}:
            return 8
        if intent in {"multi_hop", "analytical", "follow_up", "scenario", "quiz", "translation"}:
            return 10
        if intent == "unclear":
            return 3
        return 5
