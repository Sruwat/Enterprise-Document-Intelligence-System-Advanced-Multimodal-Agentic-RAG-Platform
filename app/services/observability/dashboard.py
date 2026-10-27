from __future__ import annotations

from statistics import mean
from typing import Any


class ObservabilityDashboard:
    def __init__(self, metadata_store, **components) -> None:
        self.metadata_store = metadata_store
        self.components = components

    def snapshot(self, limit: int = 200) -> dict[str, Any]:
        logs = self.metadata_store.recent_query_logs(limit=limit)
        latencies = [float((log.get("latency_ms") or {}).get("total", 0.0) or 0.0) for log in logs]
        failures = [
            log
            for log in logs
            if log.get("abstained") or float(log.get("confidence", 0.0) or 0.0) < 0.5 or log.get("grounding_status") == "blocked"
        ]
        citation_flags = [1.0 if log.get("citations") else 0.0 for log in logs]
        confidence_values = [float(log.get("confidence", 0.0) or 0.0) for log in logs]
        return {
            "query_count": len(logs),
            "latency": {
                "avg_ms": round(mean(latencies), 2) if latencies else 0.0,
                "p95_ms": self._percentile(latencies, 95),
                "p99_ms": self._percentile(latencies, 99),
            },
            "quality": {
                "avg_confidence": round(mean(confidence_values), 4) if confidence_values else 0.0,
                "citation_coverage": round(mean(citation_flags), 4) if citation_flags else 0.0,
                "failure_rate": round(len(failures) / len(logs), 4) if logs else 0.0,
            },
            "recent_failures": failures[:10],
            "health": {
                "status": "warning" if failures else "ok",
                "message": "Recent low-confidence or abstained answers detected." if failures else "Recent queries look healthy.",
            },
            "components": self._components(),
            "retrieval": self._retrieval_metrics(logs),
            "cost": self._cost_metrics(logs),
        }

    def _components(self) -> dict[str, Any]:
        vector_store = self.components.get("vector_store")
        redis_service = self.components.get("redis_service")
        graph_repository = self.components.get("graph_repository")
        primary_llm = self.components.get("primary_llm")
        huggingface_registry = self.components.get("huggingface_registry")
        worker = self.components.get("worker")
        queue = self.components.get("queue")
        query_cache = self.components.get("query_cache")
        evaluation_service = self.components.get("evaluation_service")
        return {
            "queue": queue.status() if queue is not None else {"status": "unknown"},
            "worker": worker.heartbeat() if worker is not None else {"status": "unknown"},
            "llm_provider": {
                "status": "ok" if getattr(primary_llm, "provider_name", None) else "unknown",
                "provider": getattr(primary_llm, "provider_name", None),
                "model": getattr(primary_llm, "model_name", None),
            },
            "ocr_provider": {"status": "configured", "primary": "PaddleOCR", "fallback": "Tesseract"},
            "vector_db": self._safe_status(vector_store),
            "postgres": self._metadata_status(),
            "redis": redis_service.status() if redis_service is not None else {"status": "unknown"},
            "graph_db": graph_repository.status() if graph_repository is not None else {"status": "unknown"},
            "huggingface": huggingface_registry.status() if huggingface_registry is not None else {"status": "unknown"},
            "cache": query_cache.status() if query_cache is not None else {"status": "unknown"},
            "graph_eval": evaluation_service.latest_graph_lift() if evaluation_service is not None else {"status": "unknown"},
            "recent_error_counts": {
                "failed_or_abstained_queries": len([log for log in self.metadata_store.recent_query_logs(limit=50) if log.get("abstained")]),
            },
        }

    def _retrieval_metrics(self, logs: list[dict[str, Any]]) -> dict[str, Any]:
        traces = [log.get("retrieval_metadata") or {} for log in logs]
        cache_flags = [1.0 if trace.get("cache_hit") else 0.0 for trace in traces]
        graph_selected = [
            float(((trace.get("graph_contribution") or {}).get("selected_count") or 0))
            for trace in traces
        ]
        blocked = [1.0 if log.get("grounding_status") == "blocked" or log.get("abstained") else 0.0 for log in logs]
        return {
            "cache_hit_rate": round(mean(cache_flags), 4) if cache_flags else 0.0,
            "avg_graph_selected_count": round(mean(graph_selected), 4) if graph_selected else 0.0,
            "blocked_answer_rate": round(mean(blocked), 4) if blocked else 0.0,
        }

    def _cost_metrics(self, logs: list[dict[str, Any]]) -> dict[str, Any]:
        token_counts = [float((log.get("usage") or {}).get("total_tokens", 0.0) or 0.0) for log in logs]
        return {
            "total_tokens": int(sum(token_counts)),
            "avg_tokens_per_query": round(mean(token_counts), 2) if token_counts else 0.0,
        }

    def _metadata_status(self) -> dict[str, Any]:
        try:
            tables = self.metadata_store.table_names() if hasattr(self.metadata_store, "table_names") else []
            return {"status": "ok", "tables": len(tables), "backend": self.metadata_store.__class__.__name__}
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    @staticmethod
    def _safe_status(component) -> dict[str, Any]:
        if component is None:
            return {"status": "unknown"}
        try:
            if hasattr(component, "status"):
                return component.status()
            if hasattr(component, "is_available"):
                return {"status": "ok" if component.is_available() else "error"}
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}
        return {"status": "unknown"}

    @staticmethod
    def _percentile(values: list[float], percentile: int) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, round((percentile / 100) * (len(ordered) - 1))))
        return round(ordered[index], 2)
