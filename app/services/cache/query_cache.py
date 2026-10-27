from __future__ import annotations

import hashlib
import json
from typing import Any


class QueryCache:
    def __init__(self, redis_service=None, ttl_seconds: int = 300) -> None:
        self.redis_service = redis_service
        self.ttl_seconds = ttl_seconds
        self.hits = 0
        self.misses = 0
        self.sets = 0
        self.invalidations = 0

    def key(self, *, tenant_id: str, workspace_id: str, payload: dict[str, Any]) -> str:
        stable = json.dumps(payload, sort_keys=True, default=str)
        digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()
        return f"retrieval-cache:{tenant_id}:{workspace_id}:{digest}"

    def retrieval_key(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        question: str,
        document_ids: list[str],
        route: str,
        objective_profile: str,
        analysis_mode: str,
        top_k: int,
        embedding_model: str,
        reranker_model: str,
        index_version: str | int | None,
    ) -> str:
        return self.key(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            payload={
                "question": " ".join(question.lower().split()),
                "document_ids": sorted(document_ids),
                "route": route,
                "objective_profile": objective_profile,
                "analysis_mode": analysis_mode,
                "top_k": int(top_k),
                "embedding_model": embedding_model,
                "reranker_model": reranker_model,
                "index_version": index_version,
            },
        )

    def get(self, key: str) -> Any | None:
        if self.redis_service is None or not getattr(self.redis_service, "enabled", False):
            self.misses += 1
            return None
        getter = getattr(self.redis_service, "get_json", None)
        if callable(getter):
            value = getter(key)
            if value is None:
                self.misses += 1
            else:
                self.hits += 1
            return value
        self.misses += 1
        return None

    def set(self, key: str, value: Any) -> None:
        if self.redis_service is None or not getattr(self.redis_service, "enabled", False):
            return
        setter = getattr(self.redis_service, "set_json", None)
        if callable(setter):
            setter(key, value, ttl_seconds=self.ttl_seconds)
            self.sets += 1

    def invalidate_workspace(self, *, tenant_id: str, workspace_id: str) -> int:
        prefix = f"retrieval-cache:{tenant_id}:{workspace_id}:"
        deleter = getattr(self.redis_service, "delete_prefix", None) if self.redis_service is not None else None
        deleted = int(deleter(prefix) if callable(deleter) else 0)
        self.invalidations += deleted
        return deleted

    def status(self) -> dict[str, Any]:
        return {
            "status": "ok" if self.redis_service is not None and getattr(self.redis_service, "enabled", False) else "disabled",
            "ttl_seconds": self.ttl_seconds,
            "hits": self.hits,
            "misses": self.misses,
            "sets": self.sets,
            "invalidations": self.invalidations,
        }
