from __future__ import annotations

import json
from pathlib import Path
import uuid
from datetime import datetime
from statistics import mean
from typing import Any, Callable

from app.core.schemas import EvaluationSummary, QueryResponse


REQUIRED_LAUNCH_CATEGORIES = {
    "agent_orchestration",
    "provider_json",
    "graph_memory",
    "multilingual",
    "legal",
    "research",
    "enterprise",
    "verifier",
    "citation",
    "large_pdf",
    "scanned_document",
    "table_visual",
}


class EvaluationService:
    def __init__(self, eval_logger, metadata_store, query_runner: Callable[[dict[str, Any]], Any] | None = None) -> None:
        self.eval_logger = eval_logger
        self.metadata_store = metadata_store
        self.query_runner = query_runner

    def run_seeded_evaluation(self, dataset_path: str | None = None, query_limit: int | None = None) -> dict:
        records = []
        if dataset_path:
            path = Path(dataset_path)
            if path.exists():
                records = self._load_dataset(path)
            else:
                raise ValueError(f"Evaluation dataset does not exist: {path}")
        if query_limit is not None:
            records = records[:query_limit]
        if not self.query_runner:
            dataset_profile = self.dataset_profile(records)
            summary = {
                "run_id": str(uuid.uuid4()),
                "status": "loaded",
                "dataset_size": len(records),
                "dataset_profile": dataset_profile,
                "ragas_enabled": self._is_package_available("ragas"),
                "ragchecker_enabled": self._is_package_available("ragchecker"),
                "mirage_style_checks": ["noise_vulnerability", "context_insensitivity", "misinterpretation"],
                "metrics": {},
                "case_results": [],
            }
            self.metadata_store.log_evaluation_run(summary["run_id"], summary)
            return summary
        case_results = [self._evaluate_case(record) for record in records]
        metrics = self._aggregate_case_metrics(case_results)
        dataset_profile = self.dataset_profile(records)
        summary = {
            "run_id": str(uuid.uuid4()),
            "status": "completed",
            "dataset_size": len(records),
            "dataset_profile": dataset_profile,
            "ragas_enabled": self._is_package_available("ragas"),
            "ragchecker_enabled": self._is_package_available("ragchecker"),
            "mirage_style_checks": ["noise_vulnerability", "context_insensitivity", "misinterpretation"],
            "metrics": metrics,
            "case_results": case_results,
            "created_at": datetime.utcnow().isoformat(),
        }
        self.metadata_store.log_evaluation_run(summary["run_id"], summary)
        return summary

    def metrics_snapshot(self) -> dict:
        summary = self.summarize()
        return {
            "total_queries": summary.total_queries,
            "avg_confidence": summary.avg_confidence,
            "abstention_rate": summary.abstention_rate,
            "metrics": summary.metrics,
        }

    def run_graph_lift_evaluation(self, dataset_path: str | None = None) -> dict[str, Any]:
        path = Path(dataset_path) if dataset_path else Path("data/eval_graph_memory_seed.json")
        records = self._load_dataset(path) if path.exists() else []
        case_results = []
        for record in records:
            vector_score = float(record.get("vector_only_score", 0.0) or 0.0)
            graph_score = float(record.get("graph_enabled_score", 0.0) or 0.0)
            if self.query_runner and record.get("query"):
                try:
                    vector_case = {**record, "route_hint": record.get("route_hint", "factual"), "expected_tools": ["search_documents"]}
                    graph_case = {**record, "route_hint": record.get("route_hint", "multi_hop"), "expected_tools": ["search_documents", "search_graph"]}
                    vector_result = self._evaluate_case(vector_case)
                    graph_result = self._evaluate_case(graph_case)
                    vector_score = float(vector_result["metrics"].get("graph_usage_accuracy", 0.0) + vector_result["metrics"].get("citation_coverage", 0.0)) / 2
                    graph_score = float(graph_result["metrics"].get("graph_usage_accuracy", 0.0) + graph_result["metrics"].get("citation_coverage", 0.0)) / 2
                except Exception:
                    pass
            case_results.append(
                {
                    "query": record.get("query") or record.get("question"),
                    "vector_only_score": round(vector_score, 4),
                    "graph_enabled_score": round(graph_score, 4),
                    "lift": round(graph_score - vector_score, 4),
                }
            )
        vector_avg = mean([case["vector_only_score"] for case in case_results]) if case_results else 0.0
        graph_avg = mean([case["graph_enabled_score"] for case in case_results]) if case_results else 0.0
        graph_lift = {
            "case_count": len(case_results),
            "vector_only_score": round(vector_avg, 4),
            "graph_enabled_score": round(graph_avg, 4),
            "lift": round(graph_avg - vector_avg, 4),
        }
        summary = {
            "run_id": str(uuid.uuid4()),
            "status": "completed" if case_results else "empty",
            "dataset_path": str(path),
            "dataset_size": len(records),
            "metrics": {"graph_lift": graph_lift},
            "case_results": case_results,
            "created_at": datetime.utcnow().isoformat(),
        }
        self.metadata_store.log_evaluation_run(summary["run_id"], summary)
        return summary

    def latest_graph_lift(self) -> dict[str, Any]:
        for run in self.metadata_store.list_evaluation_runs(limit=20):
            metrics = run.get("metrics") or {}
            graph = metrics.get("graph_lift") or metrics.get("graph_memory_lift") or run.get("graph_lift")
            if isinstance(graph, dict):
                lift = float(graph.get("lift", 0.0) or 0.0)
                return {
                    "run_id": run.get("run_id"),
                    "lift": lift,
                    "vector_only_score": graph.get("vector_only_score"),
                    "graph_enabled_score": graph.get("graph_enabled_score"),
                    "case_count": graph.get("case_count"),
                }
            if "graph_lift" in metrics:
                return {"run_id": run.get("run_id"), "lift": float(metrics.get("graph_lift") or 0.0)}
        return {"run_id": None, "lift": 0.0}

    def launch_gates(
        self,
        *,
        dataset_path: str | None = None,
        min_queries: int = 1,
        min_citation_coverage: float = 0.8,
        max_abstention_rate: float = 0.35,
        min_benchmark_pass_rate: float = 0.8,
        min_category_pass_rate: float = 0.75,
        require_dataset_coverage: bool = False,
    ) -> dict:
        summary = self.summarize()
        benchmark = self._latest_benchmark()
        dataset_profile = self.dataset_profile(self._load_dataset(Path(dataset_path))) if dataset_path else benchmark.get("dataset_profile", {})
        missing_categories = sorted(REQUIRED_LAUNCH_CATEGORIES - set(dataset_profile.get("categories", [])))
        category_pass_rates = benchmark.get("category_pass_rates", {})
        missing_benchmark_categories = (
            sorted(REQUIRED_LAUNCH_CATEGORIES - set(category_pass_rates))
            if require_dataset_coverage
            else []
        )
        category_values = list(category_pass_rates.values())
        category_gate_ready = bool(category_values) and not missing_benchmark_categories and min(category_values) >= min_category_pass_rate
        checks = [
            {
                "name": "minimum_query_volume",
                "status": "ok" if summary.total_queries >= min_queries else "blocker",
                "observed": summary.total_queries,
                "threshold": min_queries,
            },
            {
                "name": "citation_coverage",
                "status": "ok" if summary.metrics.get("citation_coverage", 0.0) >= min_citation_coverage else "blocker",
                "observed": summary.metrics.get("citation_coverage", 0.0),
                "threshold": min_citation_coverage,
            },
            {
                "name": "abstention_rate",
                "status": "ok" if summary.abstention_rate <= max_abstention_rate else "blocker",
                "observed": summary.abstention_rate,
                "threshold": max_abstention_rate,
            },
            {
                "name": "seeded_benchmark_pass_rate",
                "status": "ok" if benchmark.get("pass_rate", 0.0) >= min_benchmark_pass_rate else "blocker",
                "observed": benchmark.get("pass_rate", 0.0),
                "threshold": min_benchmark_pass_rate,
                "run_id": benchmark.get("run_id"),
            },
            {
                "name": "category_pass_rate",
                "status": "ok" if category_gate_ready else "blocker",
                "observed": category_pass_rates,
                "threshold": min_category_pass_rate,
                "missing_categories": missing_benchmark_categories,
                "run_id": benchmark.get("run_id"),
            },
            {
                "name": "launch_dataset_coverage",
                "status": "ok" if (not require_dataset_coverage or not missing_categories) else "blocker",
                "observed": dataset_profile,
                "missing_categories": missing_categories,
                "required_categories": sorted(REQUIRED_LAUNCH_CATEGORIES),
            },
        ]
        blockers = [check for check in checks if check["status"] == "blocker"]
        return {
            "status": "blocked" if blockers else "ready",
            "blocker_count": len(blockers),
            "checks": checks,
            "summary": summary.model_dump(),
            "benchmark": benchmark,
        }

    @staticmethod
    def _load_dataset(path: Path) -> list[dict]:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            records = []
            for line_no, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    records.append(json.loads(stripped))
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid evaluation dataset format at line {line_no} in {path}. "
                        "Expected either a JSON array or JSONL."
                    ) from exc
            return records
        if isinstance(payload, list):
            return payload
        raise ValueError(f"Invalid evaluation dataset format in {path}. Expected a JSON array or JSONL.")

    @staticmethod
    def dataset_profile(records: list[dict[str, Any]]) -> dict[str, Any]:
        categories = sorted({str(record.get("category", "factual")) for record in records})
        objective_profiles = sorted({str(record.get("objective_profile", "general")) for record in records})
        languages = sorted({str(record.get("expected_language") or record.get("response_language") or record.get("language") or "english") for record in records})
        expected_tools = sorted({tool for record in records for tool in record.get("expected_tools", [])})
        return {
            "case_count": len(records),
            "categories": categories,
            "objective_profiles": objective_profiles,
            "languages": languages,
            "expected_tools": expected_tools,
        }

    def summarize(self) -> EvaluationSummary:
        logs = self.metadata_store.recent_query_logs(limit=200)
        if not logs:
            return EvaluationSummary(
                total_queries=0,
                avg_confidence=0.0,
                abstention_rate=0.0,
                metrics={},
                recent_failures=[],
            )
        confidences = [float(log.get("confidence", 0.0)) for log in logs]
        abstentions = [1 if log.get("abstained") else 0 for log in logs]
        failures = [log for log in logs if log.get("abstained") or float(log.get("confidence", 0.0)) < 0.5][:5]
        metrics = {
            "avg_latency_total_ms": mean([float(log.get("latency_ms", {}).get("total", 0.0)) for log in logs]),
            "citation_coverage": mean([1.0 if log.get("citations") else 0.0 for log in logs]),
            "router_multi_hop_rate": mean([1.0 if log.get("route_used") == "multi_hop" else 0.0 for log in logs]),
        }
        return EvaluationSummary(
            total_queries=len(logs),
            avg_confidence=round(mean(confidences), 4),
            abstention_rate=round(mean(abstentions), 4),
            metrics=metrics,
            recent_failures=failures,
        )

    def _evaluate_case(self, record: dict[str, Any]) -> dict[str, Any]:
        response = self.query_runner(record) if self.query_runner else None
        response_payload = response.model_dump(mode="json") if hasattr(response, "model_dump") else dict(response or {})
        expected_behavior = record.get("expected_behavior", "answer")
        support = record.get("supporting_document_reference") or {}
        citations = response_payload.get("citations") or []
        retrieved = response_payload.get("retrieved_chunks") or []
        abstained = bool(response_payload.get("abstained"))
        expected_page = support.get("page_number") or support.get("page")
        expected_document = support.get("document_id") or support.get("filename")
        expected_answer = str(record.get("expected_answer") or record.get("ground_truth") or "").lower()
        answer = str(response_payload.get("answer") or "")
        answer_lower = answer.lower()
        route_used = response_payload.get("route_used") or response_payload.get("intent")
        answer_language = response_payload.get("answer_language")
        confidence = float(response_payload.get("confidence", 0.0) or 0.0)
        agent_run = response_payload.get("agent_run") or {}
        evidence_canvas = response_payload.get("evidence_canvas") or {}
        agent_steps = (agent_run.get("steps") or evidence_canvas.get("agent_steps") or response_payload.get("steps") or [])
        retrieval_metadata = response_payload.get("retrieval_metadata") or {}
        tool_names = self._tool_names(agent_steps, retrieval_metadata)
        visual_cards = response_payload.get("visual_cards") or evidence_canvas.get("visual_cards") or []
        evidence_items = response_payload.get("evidence") or evidence_canvas.get("evidence_items") or []
        citation_page_accuracy = 1.0
        if expected_page:
            citation_page_accuracy = 1.0 if any(int(citation.get("page_number", -1)) == int(expected_page) for citation in citations) else 0.0
        recall_at_k = 1.0
        if expected_document:
            recall_at_k = 1.0 if any(expected_document in {chunk.get("document_id"), chunk.get("filename")} for chunk in retrieved) else 0.0
        citation_coverage = 1.0 if citations else 0.0
        abstention_correctness = 1.0 if ((expected_behavior == "abstain") == abstained) else 0.0
        answer_match = 1.0 if expected_behavior == "abstain" or not expected_answer or expected_answer in answer_lower else 0.0
        hallucination_risk = 1.0 if expected_behavior == "abstain" and not abstained else 0.0
        expected_route = record.get("expected_route") or record.get("route_hint")
        route_accuracy = 1.0 if not expected_route or route_used == expected_route else 0.0
        expected_language = record.get("expected_language")
        language_accuracy = 1.0 if not expected_language or answer_language == expected_language else 0.0
        expected_objective = record.get("expected_objective_profile") or record.get("objective_profile")
        objective_accuracy = 1.0 if not expected_objective or retrieval_metadata.get("objective_profile") == expected_objective or (agent_run.get("objective_profile") == expected_objective) else 0.0
        expected_tools = set(record.get("expected_tools") or [])
        tool_selection_accuracy = 1.0 if not expected_tools or expected_tools <= tool_names else 0.0
        forbidden_terms = [str(term).lower() for term in record.get("forbidden_terms", [])]
        unsupported_claim_control = 1.0 if not any(term in answer_lower for term in forbidden_terms) else 0.0
        min_confidence = float(record.get("min_confidence", 0.0) or 0.0)
        confidence_gate = 1.0 if confidence >= min_confidence else 0.0
        visual_evidence_accuracy = 1.0 if not record.get("requires_visual_evidence") or bool(visual_cards) else 0.0
        graph_usage_accuracy = 1.0
        if record.get("requires_graph"):
            graph_usage_accuracy = 1.0 if "search_graph" in tool_names or "graph" in str(retrieval_metadata.get("retrieval_strategy", "")).lower() else 0.0
        missing_evidence_notes = evidence_canvas.get("missing_evidence") or []
        verifier_accuracy = 1.0
        if record.get("requires_missing_evidence_note"):
            verifier_accuracy = 1.0 if abstained or missing_evidence_notes else 0.0
        evidence_presence = 1.0 if evidence_items or citations else 0.0
        expected_agent_steps = set(record.get("expected_agent_steps") or [])
        step_names = {str(step.get("agent_name")) for step in agent_steps if isinstance(step, dict)}
        agent_trace_accuracy = 1.0 if not expected_agent_steps or expected_agent_steps <= step_names else 0.0
        category_metrics = self._category_metrics(record.get("category", "factual"), locals())
        passed = bool(
            citation_coverage >= 1.0
            and citation_page_accuracy >= 1.0
            and abstention_correctness >= 1.0
            and hallucination_risk == 0.0
            and (expected_behavior == "abstain" or answer_match >= 1.0)
            and all(value >= 1.0 for value in category_metrics.values())
        )
        return {
            "query": record.get("query") or record.get("question"),
            "category": record.get("category", "factual"),
            "objective_profile": record.get("objective_profile", "general"),
            "expected_behavior": expected_behavior,
            "passed": passed,
            "metrics": {
                "recall_at_k": recall_at_k,
                "citation_coverage": citation_coverage,
                "citation_page_accuracy": citation_page_accuracy,
                "abstention_correctness": abstention_correctness,
                "hallucination_risk": hallucination_risk,
                "answer_match": answer_match,
                "route_accuracy": route_accuracy,
                "language_accuracy": language_accuracy,
                "objective_accuracy": objective_accuracy,
                "tool_selection_accuracy": tool_selection_accuracy,
                "unsupported_claim_control": unsupported_claim_control,
                "confidence_gate": confidence_gate,
                "visual_evidence_accuracy": visual_evidence_accuracy,
                "graph_usage_accuracy": graph_usage_accuracy,
                "verifier_accuracy": verifier_accuracy,
                "evidence_presence": evidence_presence,
                "agent_trace_accuracy": agent_trace_accuracy,
                **category_metrics,
            },
        }

    @staticmethod
    def _aggregate_case_metrics(case_results: list[dict[str, Any]]) -> dict[str, float]:
        if not case_results:
            return {"pass_rate": 0.0, "recall_at_k": 0.0, "citation_coverage": 0.0, "citation_page_accuracy": 0.0, "abstention_correctness": 0.0, "hallucination_risk": 0.0}
        metric_names = sorted({name for case in case_results for name in case.get("metrics", {})})
        metrics = {name: round(mean(float(case["metrics"].get(name, 0.0)) for case in case_results), 4) for name in metric_names}
        metrics["pass_rate"] = round(mean(1.0 if case.get("passed") else 0.0 for case in case_results), 4)
        categories = sorted({case.get("category", "factual") for case in case_results})
        metrics["category_pass_rates"] = {
            category: round(mean(1.0 if case.get("passed") else 0.0 for case in case_results if case.get("category", "factual") == category), 4)
            for category in categories
        }
        return metrics

    def _latest_benchmark(self) -> dict[str, Any]:
        for run in self.metadata_store.list_evaluation_runs(limit=10):
            metrics = run.get("metrics") or {}
            if "pass_rate" in metrics:
                return {"run_id": run.get("run_id"), "dataset_profile": run.get("dataset_profile", {}), **metrics}
        return {"run_id": None, "pass_rate": 0.0}

    @staticmethod
    def _tool_names(agent_steps: list[dict[str, Any]], retrieval_metadata: dict[str, Any]) -> set[str]:
        names: set[str] = set()
        strategy = str(retrieval_metadata.get("retrieval_strategy") or "")
        if strategy:
            names.add("search_documents")
            if "graph" in strategy.lower():
                names.add("search_graph")
        for step in agent_steps:
            metadata = step.get("metadata", {}) if isinstance(step, dict) else {}
            for call in metadata.get("tool_calls", []) or []:
                if isinstance(call, dict) and call.get("tool_name"):
                    names.add(str(call["tool_name"]))
            decision = metadata.get("agent_decision") or {}
            for call in decision.get("tools", []) if isinstance(decision, dict) else []:
                if isinstance(call, dict) and call.get("tool_name"):
                    names.add(str(call["tool_name"]))
        return names

    @staticmethod
    def _category_metrics(category: str, values: dict[str, Any]) -> dict[str, float]:
        category = str(category)
        if category == "agent_orchestration":
            return {"agent_orchestration_accuracy": min(values["tool_selection_accuracy"], values["agent_trace_accuracy"])}
        if category == "provider_json":
            return {"provider_json_accuracy": values["tool_selection_accuracy"]}
        if category == "graph_memory":
            return {"graph_memory_accuracy": values["graph_usage_accuracy"]}
        if category == "multilingual":
            return {"multilingual_accuracy": values["language_accuracy"]}
        if category in {"legal", "research", "enterprise"}:
            return {f"{category}_objective_accuracy": values["objective_accuracy"]}
        if category == "verifier":
            return {"verifier_accuracy": min(values["verifier_accuracy"], values["unsupported_claim_control"])}
        if category == "citation":
            return {"citation_accuracy": min(values["citation_coverage"], values["citation_page_accuracy"])}
        if category in {"large_pdf", "scanned_document"}:
            return {f"{category}_accuracy": min(values["recall_at_k"], values["citation_page_accuracy"])}
        if category == "table_visual":
            return {"table_visual_accuracy": values["visual_evidence_accuracy"]}
        return {}

    @staticmethod
    def _is_package_available(module_name: str) -> bool:
        try:
            __import__(module_name)
            return True
        except Exception:
            return False


def heuristic_ragas_scores(response: QueryResponse) -> dict[str, float]:
    citation_ratio = min(len(response.citations) / max(len(response.retrieved_chunks), 1), 1.0)
    if response.abstained:
        return {"faithfulness": 1.0, "answer_relevance": 0.0, "context_precision": citation_ratio}
    return {
        "faithfulness": min(response.confidence + 0.1, 1.0),
        "answer_relevance": response.confidence,
        "context_precision": citation_ratio,
    }
