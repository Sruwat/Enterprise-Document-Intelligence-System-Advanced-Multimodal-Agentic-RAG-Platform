from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class RetentionPolicy:
    scope: str
    default_retention_days: int | None = None
    temporary_retention_hours: int = 24
    allow_user_delete: bool = True
    admin_only_delete: bool = False
    approval_required: bool = False
    retention_locked: bool = False
    external_processing_allowed: bool = True
    private_llm_required: bool = False
    private_embedding_required: bool = False
    private_ocr_required: bool = False
    cache_allowed: bool = True
    chat_retention_days: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class RetentionPolicyEngine:
    """Resolves retention from workspace defaults and document overrides.

    Policy decisions are server-side and deterministic. A browser timer is never
    used as the source of truth for expiry.
    """

    def __init__(self, settings=None) -> None:
        self.settings = settings

    def resolve(self, *, workspace=None, document=None) -> RetentionPolicy:
        workspace_meta = dict(getattr(workspace, "metadata", {}) or {})
        document_meta = dict(getattr(document, "metadata", {}) or {})
        values = {
            "default_retention_days": workspace_meta.get("default_retention_days"),
            "temporary_retention_hours": workspace_meta.get("temporary_retention_hours", 24),
            "allow_user_delete": workspace_meta.get("allow_user_delete", True),
            "admin_only_delete": workspace_meta.get("admin_only_delete", False),
            "approval_required": workspace_meta.get("approval_required", False),
            "retention_locked": workspace_meta.get("retention_locked", False),
            "external_processing_allowed": getattr(workspace, "external_ai_allowed", True),
            "private_llm_required": False,
            "private_embedding_required": False,
            "private_ocr_required": False,
            "cache_allowed": True,
            "chat_retention_days": getattr(self.settings, "chat_retention_days", None),
        }
        for key in list(values):
            if key in document_meta and document_meta[key] is not None:
                values[key] = document_meta[key]
        if document_meta.get("external_processing_allowed") is not None:
            values["external_processing_allowed"] = bool(document_meta["external_processing_allowed"])
        if document_meta.get("classification") in {"highly_confidential", "regulated"}:
            values.update(
                external_processing_allowed=False,
                private_llm_required=True,
                private_embedding_required=True,
                private_ocr_required=True,
            )
        if getattr(workspace, "private_mode", False):
            values.update(external_processing_allowed=False, private_llm_required=True, private_embedding_required=True, private_ocr_required=True)
        mode = document_meta.get("document_mode", "knowledge_base")
        scope = "document" if document is not None else "workspace"
        return RetentionPolicy(scope=scope, **values)

    def expiry_for(self, *, mode: str, retention: str | None, policy: RetentionPolicy, now: datetime | None = None) -> datetime | None:
        if mode != "temporary_analysis":
            if policy.default_retention_days is None:
                return None
            return (now or datetime.utcnow()) + timedelta(days=int(policy.default_retention_days))
        current = now or datetime.utcnow()
        normalized = (retention or "24h").strip().lower()
        if normalized in {"session", "delete_after_session", "end_of_session"}:
            return current + timedelta(hours=policy.temporary_retention_hours)
        mapping = {"1h": 1, "1 hour": 1, "24h": 24, "24 hours": 24, "7d": 168, "7 days": 168, "30d": 720, "30 days": 720}
        if normalized in mapping:
            return current + timedelta(hours=mapping[normalized])
        try:
            return datetime.fromisoformat(retention or "")
        except ValueError:
            return current + timedelta(hours=policy.temporary_retention_hours)
