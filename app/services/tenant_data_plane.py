from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TenantDataPlane:
    tenant_id: str
    mode: str
    postgres_secret_ref: str | None = None
    redis_secret_ref: str | None = None
    qdrant_endpoint_ref: str | None = None
    storage_bucket: str | None = None
    kms_key_ref: str | None = None
    llm_policy: dict[str, Any] | None = None


class TenantDataPlaneResolver:
    """Resolves references, never raw secrets, for shared/dedicated data planes.

    Shared mode is the current live default. Dedicated mode is a deployment
    contract: provisioning and secret retrieval stay with the cloud platform.
    """

    def __init__(self, *, default_mode: str = "shared", registry=None) -> None:
        self.default_mode = default_mode if default_mode in {"shared", "dedicated"} else "shared"
        self.registry = registry or {}

    def resolve(self, tenant_id: str) -> TenantDataPlane:
        value = self.registry.get(tenant_id) or {}
        mode = value.get("mode", self.default_mode)
        if mode not in {"shared", "dedicated"}:
            raise ValueError(f"Unsupported tenant data plane mode: {mode}")
        return TenantDataPlane(tenant_id=tenant_id, mode=mode, postgres_secret_ref=value.get("postgres_secret_ref"), redis_secret_ref=value.get("redis_secret_ref"), qdrant_endpoint_ref=value.get("qdrant_endpoint_ref"), storage_bucket=value.get("storage_bucket"), kms_key_ref=value.get("kms_key_ref"), llm_policy=value.get("llm_policy") or {})
