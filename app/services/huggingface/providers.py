from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HuggingFaceTaskProvider:
    task: str
    model_id: str
    local_path: str | None = None
    enabled: bool = False
    max_seconds: int = 30
    max_memory_mb: int = 4096
    _pipeline: Any = field(default=None, compare=False, repr=False)
    _last_error: str | None = field(default=None, compare=False)

    def status(self) -> dict[str, Any]:
        local_exists = bool(self.local_path and Path(self.local_path).exists())
        return {
            "task": self.task,
            "model_id": self.model_id,
            "local_path": self.local_path,
            "enabled": self.enabled,
            "status": "ready" if self.enabled and self._pipeline is not None else "configured" if self.enabled and (local_exists or not self.local_path) else "degraded" if self.enabled else "disabled",
            "local_exists": local_exists,
            "max_seconds": self.max_seconds,
            "max_memory_mb": self.max_memory_mb,
            "last_error": self._last_error,
        }

    def run(self, payload: Any) -> dict[str, Any]:
        if not self.enabled:
            return self._fallback(payload, "provider disabled")
        started = time.perf_counter()
        try:
            pipeline = self._load_pipeline()
            if pipeline is None:
                return self._fallback(payload, self._last_error or "pipeline unavailable")
            output = pipeline(payload)
            elapsed = time.perf_counter() - started
            if elapsed > self.max_seconds:
                return self._fallback(payload, f"execution exceeded {self.max_seconds}s")
            return {"task": self.task, "model_id": self.model_id, "status": "ready", "output": output, "latency_ms": round(elapsed * 1000, 2)}
        except Exception as exc:
            object.__setattr__(self, "_last_error", str(exc))
            return self._fallback(payload, str(exc))

    def _load_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        try:
            from transformers import pipeline

            task_name = {
                "entity_extraction": "token-classification",
                "document_classification": "zero-shot-classification",
                "evidence_checking": "zero-shot-classification",
                "image_captioning": "image-to-text",
                "ocr_vlm": "image-to-text",
            }.get(self.task)
            if task_name is None:
                object.__setattr__(self, "_last_error", "task requires a specialized adapter")
                return None
            if not self.local_path or not Path(self.local_path).exists():
                object.__setattr__(self, "_last_error", "local model path is missing")
                return None
            model_ref = self.local_path
            loaded = pipeline(task_name, model=model_ref, aggregation_strategy="simple" if task_name == "token-classification" else None)
            object.__setattr__(self, "_pipeline", loaded)
            object.__setattr__(self, "_last_error", None)
            return loaded
        except Exception as exc:
            object.__setattr__(self, "_last_error", str(exc))
            return None

    def _fallback(self, payload: Any, detail: str) -> dict[str, Any]:
        return {
            "task": self.task,
            "model_id": self.model_id,
            "status": "fallback",
            "output": payload,
            "detail": f"Deterministic fallback used: {detail}",
        }


class HuggingFaceProviderRegistry:
    DEFAULT_MODELS = {
        "embedding": "BAAI/bge-m3",
        "reranking": "BAAI/bge-reranker-v2-m3",
        "ocr_vlm": "microsoft/trocr-base-printed",
        "image_captioning": "Salesforce/blip-image-captioning-base",
        "table_extraction": "microsoft/table-transformer-detection",
        "entity_extraction": "dslim/bert-base-NER",
        "document_classification": "facebook/bart-large-mnli",
        "evidence_checking": "MoritzLaurer/deberta-v3-base-zeroshot-v1.1-all-33",
    }

    def __init__(
        self,
        *,
        enabled: bool = False,
        cache_dir: str | Path = "./models/huggingface",
        overrides: dict[str, str] | None = None,
        task_enables: dict[str, bool] | None = None,
        max_seconds: int = 30,
        max_memory_mb: int = 4096,
    ) -> None:
        self.enabled = enabled
        self.cache_dir = Path(cache_dir)
        self.overrides = overrides or {}
        self.task_enables = task_enables or {}
        self.max_seconds = max_seconds
        self.max_memory_mb = max_memory_mb

    def provider_for(self, task: str) -> HuggingFaceTaskProvider:
        model_id = self.overrides.get(task) or self.DEFAULT_MODELS.get(task, "")
        local_path = self.cache_dir / model_id.replace("/", "__") if model_id else None
        enabled = self.enabled and bool(model_id) and self.task_enables.get(task, True)
        return HuggingFaceTaskProvider(task=task, model_id=model_id, local_path=str(local_path) if local_path else None, enabled=enabled, max_seconds=self.max_seconds, max_memory_mb=self.max_memory_mb)

    def status(self) -> dict[str, Any]:
        providers = {task: self.provider_for(task).status() for task in self.DEFAULT_MODELS}
        ready_count = sum(1 for item in providers.values() if item["status"] == "ready")
        error_count = sum(1 for item in providers.values() if item["status"] in {"degraded"} or item.get("last_error"))
        return {
            "enabled": self.enabled,
            "cache_dir": str(self.cache_dir),
            "ready_count": ready_count,
            "error_count": error_count,
            "provider_count": len(providers),
            "providers": providers,
        }

    def extract_entities(self, text: str) -> dict[str, Any]:
        import re

        entities = []
        for match in re.findall(r"\b[A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]+){0,3}\b", text):
            if match not in {"The", "This", "That", "Source"} and match not in entities:
                entities.append(match)
        provider = self.provider_for("entity_extraction")
        return {"entities": entities[:40], "provider": provider.model_id, "status": provider.status()["status"]}

    def check_evidence(self, *, answer: str, evidence: list[str]) -> dict[str, Any]:
        answer_tokens = {token.lower() for token in answer.split() if len(token) > 3}
        evidence_text = " ".join(evidence).lower()
        matched = sum(1 for token in answer_tokens if token in evidence_text)
        score = matched / max(len(answer_tokens), 1)
        provider = self.provider_for("evidence_checking")
        return {
            "supported": score >= 0.35,
            "score": round(score, 4),
            "provider": provider.model_id,
            "status": provider.status()["status"],
        }

    def rerank(self, query: str, documents: list[str], *, top_n: int = 5) -> dict[str, Any]:
        query_tokens = {token.lower() for token in query.split() if len(token) > 2}
        scored = []
        for index, document in enumerate(documents):
            doc_tokens = set(document.lower().split())
            score = len(query_tokens & doc_tokens) / max(len(query_tokens), 1)
            scored.append({"index": index, "score": round(score, 4), "text": document})
        provider = self.provider_for("reranking")
        return {
            "results": sorted(scored, key=lambda item: item["score"], reverse=True)[:top_n],
            "provider": provider.model_id,
            "status": provider.status()["status"],
        }

    def classify_document(self, text: str) -> dict[str, Any]:
        lowered = text.lower()
        if any(term in lowered for term in ("agreement", "clause", "termination", "liability")):
            label = "legal"
        elif any(term in lowered for term in ("policy", "control", "audit", "compliance")):
            label = "enterprise"
        elif any(term in lowered for term in ("research", "finding", "method", "study")):
            label = "research"
        else:
            label = "general"
        return {"label": label, "confidence": 0.55, "provider": "heuristic_hf_registry_fallback"}
