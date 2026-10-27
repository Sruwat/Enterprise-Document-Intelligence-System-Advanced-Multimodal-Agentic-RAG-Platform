from __future__ import annotations

import json
import time
from typing import Any


class RedisService:
    def __init__(self, url: str, enabled: bool = False) -> None:
        self.url = url
        self.enabled = enabled
        self._client = None

    def _load(self):
        if not self.enabled:
            return None
        if self._client is None:
            try:
                import redis

                self._client = redis.Redis.from_url(self.url, decode_responses=True)
            except Exception:
                self._client = None
        return self._client

    def status(self) -> dict[str, Any]:
        if not self.enabled:
            return {"status": "disabled", "enabled": False, "url": self.url}
        client = self._load()
        if client is None:
            return {"status": "error", "enabled": True, "url": self.url, "detail": "redis package/client unavailable"}
        try:
            client.ping()
        except Exception as exc:
            return {"status": "error", "enabled": True, "url": self.url, "detail": str(exc)}
        return {"status": "ok", "enabled": True, "url": self.url}

    def get_json(self, key: str) -> Any | None:
        client = self._load()
        if client is None:
            return None
        try:
            raw = client.get(key)
        except Exception:
            self._client = None
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        client = self._load()
        if client is None:
            return
        payload = json.dumps(value, default=str)
        try:
            if ttl_seconds:
                client.setex(key, ttl_seconds, payload)
            else:
                client.set(key, payload)
        except Exception:
            self._client = None

    def delete(self, key: str) -> None:
        client = self._load()
        if client is None:
            return
        try:
            client.delete(key)
        except Exception:
            self._client = None

    def delete_prefix(self, prefix: str) -> int:
        client = self._load()
        if client is None:
            return 0
        deleted = 0
        cursor = 0
        pattern = f"{prefix}*"
        while True:
            try:
                cursor, keys = client.scan(cursor=cursor, match=pattern, count=200)
                if keys:
                    deleted += int(client.delete(*keys))
            except Exception:
                self._client = None
                return deleted
            if cursor == 0:
                break
        return deleted

    @staticmethod
    def tenant_key(tenant_id: str, workspace_id: str | None, kind: str, identifier: str) -> str:
        safe_tenant = "".join(ch for ch in tenant_id if ch.isalnum() or ch in {"-", "_"}) or "default-tenant"
        safe_workspace = "".join(ch for ch in (workspace_id or "global") if ch.isalnum() or ch in {"-", "_"}) or "global"
        safe_identifier = "".join(ch for ch in identifier if ch.isalnum() or ch in {"-", "_", ":"}) or "unknown"
        return f"tenant:{safe_tenant}:workspace:{safe_workspace}:{kind}:{safe_identifier}"

    def set_ingestion_progress(self, job_id: str, payload: dict[str, Any], ttl_seconds: int = 60 * 60 * 24, *, tenant_id: str | None = None, workspace_id: str | None = None) -> None:
        if tenant_id or workspace_id:
            self.set_json(self.tenant_key(tenant_id or "default-tenant", workspace_id, "ingestion_progress", job_id), payload, ttl_seconds=ttl_seconds)
        self.set_json(f"ingest:{job_id}:progress", payload, ttl_seconds=ttl_seconds)

    def get_ingestion_progress(self, job_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None) -> dict[str, Any] | None:
        payload = None
        if tenant_id or workspace_id:
            payload = self.get_json(self.tenant_key(tenant_id or "default-tenant", workspace_id, "ingestion_progress", job_id))
        if payload is None:
            payload = self.get_json(f"ingest:{job_id}:progress")
        return payload if isinstance(payload, dict) else None

    def set_agent_state(self, run_id: str, payload: dict[str, Any], ttl_seconds: int = 60 * 60 * 6, *, tenant_id: str | None = None, workspace_id: str | None = None) -> None:
        if tenant_id or workspace_id:
            self.set_json(self.tenant_key(tenant_id or "default-tenant", workspace_id, "agent_state", run_id), payload, ttl_seconds=ttl_seconds)
        self.set_json(f"agent:{run_id}:state", payload, ttl_seconds=ttl_seconds)

    def get_agent_state(self, run_id: str, *, tenant_id: str | None = None, workspace_id: str | None = None) -> dict[str, Any] | None:
        payload = None
        if tenant_id or workspace_id:
            payload = self.get_json(self.tenant_key(tenant_id or "default-tenant", workspace_id, "agent_state", run_id))
        if payload is None:
            payload = self.get_json(f"agent:{run_id}:state")
        return payload if isinstance(payload, dict) else None

    def set_retrieval_cache(self, tenant_id: str, workspace_id: str, query_hash: str, payload: Any, ttl_seconds: int = 10 * 60) -> None:
        self.set_json(f"retrieval:{tenant_id}:{workspace_id}:{query_hash}", payload, ttl_seconds=ttl_seconds)

    def get_retrieval_cache(self, tenant_id: str, workspace_id: str, query_hash: str) -> Any | None:
        return self.get_json(f"retrieval:{tenant_id}:{workspace_id}:{query_hash}")

    def append_json(self, key: str, value: Any, max_items: int = 50, ttl_seconds: int | None = None) -> None:
        current = self.get_json(key) or []
        if not isinstance(current, list):
            current = []
        current.append(value)
        self.set_json(key, current[-max_items:], ttl_seconds=ttl_seconds)

    def enqueue_json(self, queue_name: str, value: Any) -> bool:
        client = self._load()
        if client is None:
            return False
        try:
            client.rpush(queue_name, json.dumps(value, default=str))
            return True
        except Exception:
            self._client = None
            return False

    def dequeue_json(self, queue_name: str, timeout_seconds: int = 1) -> Any | None:
        client = self._load()
        if client is None:
            return None
        try:
            item = client.blpop(queue_name, timeout=timeout_seconds)
        except Exception:
            self._client = None
            return None
        if not item:
            return None
        _, raw = item
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def queue_length(self, queue_name: str) -> int:
        client = self._load()
        if client is None:
            return 0
        try:
            return int(client.llen(queue_name))
        except Exception:
            self._client = None
            return 0

    def rate_limit(self, key: str, limit: int, window_seconds: int, *, tenant_id: str | None = None, workspace_id: str | None = None) -> tuple[bool, int]:
        client = self._load()
        if client is None:
            return True, limit
        now = int(time.time())
        scoped_key = self.tenant_key(tenant_id or "global", workspace_id, "rate", key) if tenant_id or workspace_id else key
        bucket = f"{scoped_key}:{now // window_seconds}"
        try:
            count = int(client.incr(bucket))
            if count == 1:
                client.expire(bucket, window_seconds + 5)
            return count <= limit, max(0, limit - count)
        except Exception:
            self._client = None
            return True, limit
