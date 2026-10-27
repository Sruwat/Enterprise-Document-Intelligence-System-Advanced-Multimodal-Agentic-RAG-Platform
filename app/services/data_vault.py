from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.schemas import DataFootprintSummary, DataLineage, DataLineageStage, DataVaultOverview, DocumentRecord, PurgeJobRecord, UserRecord
from app.services.retention import RetentionPolicyEngine


class DataVaultService:
    def __init__(self, *, metadata_store, vector_store=None, graph_repository=None, settings=None) -> None:
        self.metadata_store = metadata_store
        self.vector_store = vector_store
        self.graph_repository = graph_repository
        self.settings = settings

    def overview(self, *, workspace_id: str, tenant_id: str) -> DataVaultOverview:
        workspace = self.metadata_store.get_workspace(workspace_id)
        documents = self.metadata_store.list_documents(workspace_id=workspace_id)
        footprints = [self.document_footprint(document=document, tenant_id=tenant_id) for document in documents]
        purge_jobs = self.metadata_store.list_purge_jobs(workspace_id, limit=1000) if hasattr(self.metadata_store, "list_purge_jobs") else []
        now = datetime.utcnow()
        expiring = sum(1 for item in footprints if item.retention_policy.get("expires_at") and _parse_datetime(item.retention_policy.get("expires_at")) and _parse_datetime(item.retention_policy.get("expires_at")) <= now)
        privacy_summary: dict[str, int] = {}
        providers: dict[str, set[str]] = {"ocr": set(), "embedding": set(), "llm": set()}
        for item in footprints:
            boundary = item.privacy_boundary
            privacy_summary[_privacy_label(item)] = privacy_summary.get(_privacy_label(item), 0) + 1
            for key, provider_key in (("ocr", "ocr"), ("embedding", "embeddings"), ("llm", "llm")):
                value = boundary.get(provider_key)
                if value:
                    providers[key].add(str(value))
        return DataVaultOverview(
            workspace_id=workspace_id,
            tenant_id=tenant_id,
            documents=len(documents),
            original_storage_bytes=_sum_known([item.original_bytes for item in footprints]),
            extracted_content_bytes=sum(item.extracted_text_bytes for item in footprints),
            indexed_chunks=sum(item.chunk_count for item in footprints),
            vector_embeddings=_sum_known([item.vector_count for item in footprints]),
            ocr_pages=sum(item.ocr_pages for item in footprints),
            graph_entities=_sum_known([item.graph_entity_count for item in footprints]),
            graph_relationships=_sum_known([item.graph_relation_count for item in footprints]),
            chats=len(self.metadata_store.list_chat_sessions(workspace_id, limit=10_000)) if hasattr(self.metadata_store, "list_chat_sessions") else None,
            temporary_documents=sum(1 for item in footprints if item.document_mode == "temporary_analysis"),
            retention_policy=_workspace_retention_policy(workspace, self.settings),
            privacy_mode="private" if workspace and (workspace.private_mode or not workspace.external_ai_allowed) else "external_allowed",
            llm_provider_mode=getattr(self.settings, "llm_privacy_mode", "unknown") if self.settings else "unknown",
            embedding_provider_mode=getattr(self.settings, "embedding_provider", "unknown") if self.settings else "unknown",
            storage_backend=getattr(self.settings, "object_storage_backend", "unknown") if self.settings else "unknown",
            pending_purges=sum(1 for job in purge_jobs if job.status in {"queued", "processing", "partial", "retrying"}),
            retention_expirations=expiring,
            privacy_summary=privacy_summary,
            provider_summary={key: sorted(values) for key, values in providers.items()},
            documents_footprint=footprints,
        )

    def lineage(self, *, document: DocumentRecord, tenant_id: str) -> DataLineage:
        processing = document.metadata.get("processing_metadata", {}) or {}
        pages = document.metadata.get("page_asset_refs", []) or []
        chunks = self.metadata_store.list_chunks(document_id=document.document_id)
        footprint = self.document_footprint(document=document, tenant_id=tenant_id)
        graph = self._graph_counts(tenant_id=tenant_id, workspace_id=document.workspace_id, document_id=document.document_id)
        stages = [
            DataLineageStage(stage="original", status="stored" if _file_size(document.source_path) is not None else "unavailable", bytes=footprint.original_bytes, details={"source": document.source_path}),
            DataLineageStage(stage="extraction", status="complete" if document.page_count else "pending", count=document.page_count, bytes=footprint.extracted_text_bytes, provider=processing.get("parser_provider")),
            DataLineageStage(stage="ocr", status=_ocr_status(pages), count=footprint.ocr_pages, provider=processing.get("ocr_provider"), boundary=_boundary(processing.get("ocr_provider")), details={"failed_pages": processing.get("ocr_failed_pages", [])}),
            DataLineageStage(stage="chunks", status="complete" if chunks else "pending", count=len(chunks)),
            DataLineageStage(stage="embeddings", status="indexed" if footprint.vector_count is not None else "unknown", count=footprint.vector_count, provider=processing.get("embedding_provider"), boundary=_boundary(processing.get("embedding_provider"))),
            DataLineageStage(stage="vector_db", status="indexed" if footprint.vector_count is not None else "unknown", count=footprint.vector_count, provider=getattr(self.settings, "qdrant_collection", None) if self.settings else None, details={"index_version": document.metadata.get("index_version", "unknown")}),
            DataLineageStage(stage="graph", status="indexed" if graph is not None else "unknown", count=(graph or {}).get("entities") if graph else None, details={"relationships": (graph or {}).get("relationships") if graph else None}),
            DataLineageStage(stage="rag", status="available" if document.status == "indexed" else "pending", details={"chat_reference_count": footprint.chat_reference_count}),
        ]
        return DataLineage(document_id=document.document_id, workspace_id=document.workspace_id, tenant_id=tenant_id, filename=document.filename, stages=stages, generated_at=datetime.utcnow())

    def document_footprint(self, *, document: DocumentRecord, tenant_id: str) -> DataFootprintSummary:
        chunks = self.metadata_store.list_chunks(document_id=document.document_id)
        page_refs = document.metadata.get("page_asset_refs", []) or []
        graph_counts = self._graph_counts(tenant_id=tenant_id, workspace_id=document.workspace_id, document_id=document.document_id)
        vector_count = self._vector_count(tenant_id=tenant_id, workspace_id=document.workspace_id, document_id=document.document_id)
        return DataFootprintSummary(
            document_id=document.document_id,
            filename=document.filename,
            status=document.status,
            document_mode=document.metadata.get("document_mode", "knowledge_base"),
            classification=document.metadata.get("classification", "internal"),
            original_bytes=_file_size(document.source_path),
            extracted_text_bytes=sum(len(chunk.text.encode("utf-8")) for chunk in chunks),
            page_count=document.page_count,
            ocr_pages=sum(1 for page in page_refs if page.get("ocr_attempted") or page.get("ocr_available")),
            chunk_count=len(chunks),
            vector_count=vector_count,
            graph_entity_count=graph_counts.get("entities") if graph_counts is not None else None,
            graph_relation_count=graph_counts.get("relationships") if graph_counts is not None else None,
            chat_reference_count=None,
            retention_policy=_document_retention_policy(document, self.settings),
            privacy_boundary=_privacy_boundary(document, self.settings),
            indexed_at=document.ingested_at if document.status == "indexed" else None,
            updated_at=document.updated_at,
        )

    def _vector_count(self, *, tenant_id: str, workspace_id: str, document_id: str) -> int | None:
        if self.vector_store is None or not hasattr(self.vector_store, "count"):
            return None
        try:
            return int(self.vector_store.count({"tenant_id": tenant_id, "workspace_id": workspace_id, "document_id": document_id}))
        except Exception:
            return None

    def _graph_counts(self, *, tenant_id: str, workspace_id: str, document_id: str) -> dict[str, int] | None:
        counter = getattr(self.graph_repository, "document_counts", None)
        if not callable(counter):
            return None
        try:
            return counter(tenant_id=tenant_id, workspace_id=workspace_id, document_id=document_id)
        except Exception:
            return None

    def export_metadata(self, *, workspace_id: str, tenant_id: str) -> dict[str, Any]:
        overview = self.overview(workspace_id=workspace_id, tenant_id=tenant_id)
        purge_jobs = [job.model_dump(mode="json") for job in self.metadata_store.list_purge_jobs(workspace_id, limit=1000)] if hasattr(self.metadata_store, "list_purge_jobs") else []
        return {"workspace_id": workspace_id, "tenant_id": tenant_id, "documents": [item.model_dump(mode="json") for item in overview.documents_footprint], "overview": overview.model_dump(mode="json"), "deletion_receipts": purge_jobs, "exported_at": datetime.utcnow().isoformat()}


class DocumentPurgeService:
    def __init__(self, *, metadata_store, vector_store, sparse_store, query_cache, graph_repository, settings) -> None:
        self.metadata_store = metadata_store
        self.vector_store = vector_store
        self.sparse_store = sparse_store
        self.query_cache = query_cache
        self.graph_repository = graph_repository
        self.settings = settings

    def purge(self, *, document: DocumentRecord, tenant_id: str, user: UserRecord, reason: str) -> PurgeJobRecord:
        existing_jobs = self.metadata_store.list_purge_jobs(document.workspace_id, limit=1000) if hasattr(self.metadata_store, "list_purge_jobs") else []
        for existing in existing_jobs:
            if existing.document_id == document.document_id and existing.status == "completed":
                return existing
        job = PurgeJobRecord(
            purge_job_id=str(uuid.uuid4()),
            workspace_id=document.workspace_id,
            document_id=document.document_id,
            status="processing",
            reason=reason,
            requested_by=user.user_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        stages: dict[str, Any] = {}
        errors: list[str] = []
        chunks = self.metadata_store.list_chunks(document_id=document.document_id)
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        try:
            try:
                self.vector_store.delete(chunk_ids)
                stages["vectors"] = {"status": "deleted", "count": len(chunk_ids)}
            except Exception as exc:
                stages["vectors"] = {"status": "failed", "count": len(chunk_ids), "error": str(exc)}
                errors.append("qdrant_vectors")
            try:
                self.sparse_store.remove_documents(chunk_ids)
                stages["sparse_index"] = {"status": "deleted", "count": len(chunk_ids)}
            except Exception as exc:
                stages["sparse_index"] = {"status": "failed", "error": str(exc)}
                errors.append("bm25")
            graph_cleanup = {"status": "unavailable"}
            cleaner = getattr(self.graph_repository, "delete_document_graph", None)
            if callable(cleaner):
                try:
                    graph_cleanup = {"status": "deleted", **cleaner(tenant_id=tenant_id, workspace_id=document.workspace_id, document_id=document.document_id)}
                except Exception as exc:
                    graph_cleanup = {"status": "failed", "error": str(exc)}
                    errors.append("graph")
            stages["graph"] = graph_cleanup
            chunk_ids_deleted = self.metadata_store.delete_document(document.document_id, document.workspace_id)
            stages["metadata"] = {"status": "deleted", "chunks": len(chunk_ids_deleted)}
            stages["original"] = _delete_managed_file(Path(document.source_path), Path(self.settings.upload_dir))
            preview_results = []
            for page in document.metadata.get("page_asset_refs", []) or []:
                preview_path = page.get("preview_path")
                if preview_path:
                    preview_results.append(_delete_managed_file(Path(preview_path), Path(self.settings.data_dir) / "previews"))
            stages["previews"] = {"status": "deleted", "count": sum(1 for item in preview_results if item.get("status") == "deleted")}
            try:
                invalidated = self.query_cache.invalidate_workspace(tenant_id=tenant_id, workspace_id=document.workspace_id)
                stages["caches"] = {"status": "invalidated", "count": invalidated}
            except Exception as exc:
                stages["caches"] = {"status": "failed", "error": str(exc)}
                errors.append("cache")
        except Exception as exc:
            errors.append("metadata")
            job.error = str(exc)
        job.status = "partial" if errors and stages else "failed" if errors else "completed"
        job.updated_at = datetime.utcnow()
        verification = self._verify_purge(document=document, tenant_id=tenant_id, chunk_ids=chunk_ids)
        if not verification["verified"] and not errors:
            errors.append("verification")
        job.status = "partial" if errors and stages else "failed" if errors else "completed"
        job.receipt = {
            "receipt_id": job.purge_job_id,
            "tenant_id": tenant_id,
            "workspace_id": document.workspace_id,
            "initiated_by": user.user_id,
            "document_id": document.document_id,
            "filename": document.filename,
            "reason": reason,
            "completed_at": job.updated_at.isoformat(),
            "stages": stages,
            "errors": errors,
            "verification_status": "verified_purged" if verification["verified"] else "not_verified",
            "verification": verification,
            "backup_retention_note": "Production deletion does not erase encrypted backup copies before their configured retention expires.",
        }
        self._record(job, user=user)
        return job

    def _verify_purge(self, *, document: DocumentRecord, tenant_id: str, chunk_ids: list[str]) -> dict[str, Any]:
        remaining_chunks = self.metadata_store.list_chunks(document_id=document.document_id)
        remaining_vectors = None
        try:
            remaining_vectors = self.vector_store.count({"tenant_id": tenant_id, "workspace_id": document.workspace_id, "document_id": document.document_id})
        except Exception:
            remaining_vectors = None
        graph_remaining = None
        counter = getattr(self.graph_repository, "document_counts", None)
        if callable(counter):
            try:
                graph_remaining = counter(tenant_id=tenant_id, workspace_id=document.workspace_id, document_id=document.document_id)
            except Exception:
                graph_remaining = None
        source_present = Path(document.source_path).exists()
        verified = not remaining_chunks and not source_present and (remaining_vectors in (None, 0)) and (graph_remaining is None or sum(graph_remaining.values()) == 0)
        return {"verified": verified, "remaining_chunks": len(remaining_chunks), "remaining_vectors": remaining_vectors, "remaining_graph": graph_remaining, "original_present": source_present}

    def purge_expired_temporary_documents(self, *, tenant_id: str, user: UserRecord | None = None) -> list[PurgeJobRecord]:
        jobs = []
        now = datetime.utcnow()
        actor = user or UserRecord(user_id="system", tenant_id=tenant_id, email="system@aiwana.local", created_at=now)
        for document in self.metadata_store.list_documents():
            if document.metadata.get("document_mode") != "temporary_analysis":
                continue
            expires_at = document.metadata.get("expires_at")
            try:
                expiry = datetime.fromisoformat(str(expires_at))
            except Exception:
                continue
            if expiry <= now:
                jobs.append(self.purge(document=document, tenant_id=tenant_id, user=actor, reason="retention_policy"))
        return jobs

    def _record(self, job: PurgeJobRecord, *, user: UserRecord) -> None:
        recorder = getattr(self.metadata_store, "upsert_purge_job", None)
        if callable(recorder):
            recorder(job)
        self.metadata_store.add_audit_log(
            "data_vault.purge_document",
            user=user,
            workspace_id=job.workspace_id,
            resource_type="document",
            resource_id=job.document_id,
            status="success" if job.status == "completed" else "failure",
            metadata={"purge_job_id": job.purge_job_id, "status": job.status, "receipt": job.receipt},
        )


def _file_size(path: str | os.PathLike | None) -> int | None:
    if not path:
        return None
    try:
        candidate = Path(path)
        return candidate.stat().st_size if candidate.exists() and candidate.is_file() else None
    except Exception:
        return None


def _sum_known(values: list[int | None]) -> int | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def _parse_datetime(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _privacy_label(item: DataFootprintSummary) -> str:
    boundary = item.privacy_boundary
    if boundary.get("private_processing_required") and boundary.get("external_data_transfer") == "no":
        return "private"
    if boundary.get("external_data_transfer") == "yes":
        return "external"
    if boundary.get("external_data_transfer") == "unknown":
        return "unknown"
    return "mixed"


def _boundary(provider: str | None) -> str | None:
    if not provider:
        return None
    return "local" if any(token in provider.lower() for token in ("local", "private", "bedrock", "vllm", "paddle", "tesseract")) else "external"


def _ocr_status(pages: list[dict[str, Any]]) -> str:
    if not pages:
        return "not_reported"
    failed = [page for page in pages if page.get("ocr_error") or page.get("ocr_status") == "failed"]
    attempted = [page for page in pages if page.get("ocr_attempted") or page.get("ocr_available")]
    if failed:
        return "partial_failure"
    if attempted:
        return "complete"
    return "not_required"


def _document_retention_policy(document: DocumentRecord, settings) -> dict[str, Any]:
    mode = document.metadata.get("document_mode", "knowledge_base")
    return {
        "mode": mode,
        "expires_at": document.metadata.get("expires_at"),
        "retention_days": document.metadata.get("retention_days")
        or (getattr(settings, "deleted_document_retention_days", None) if mode == "temporary_analysis" else None),
    }


def _workspace_retention_policy(workspace, settings) -> dict[str, Any]:
    metadata = workspace.metadata if workspace else {}
    return {
        "default_document_mode": metadata.get("default_document_mode", "knowledge_base"),
        "temporary_retention_days": metadata.get("temporary_retention_days", getattr(settings, "deleted_document_retention_days", None)),
        "chat_retention_days": getattr(settings, "chat_retention_days", None),
        "query_log_retention_days": getattr(settings, "query_log_retention_days", None),
        "audit_retention_days": getattr(settings, "audit_retention_days", None),
    }


def _privacy_boundary(document: DocumentRecord, settings) -> dict[str, Any]:
    processing = document.metadata.get("processing_metadata", {})
    llm_mode = getattr(settings, "llm_privacy_mode", "unknown") if settings else "unknown"
    return {
        "ocr": processing.get("ocr_provider", "local_worker_or_unavailable"),
        "embeddings": processing.get("embedding_provider") or getattr(settings, "embedding_provider", "unknown"),
        "llm": processing.get("llm_provider") or getattr(settings, "llm_provider", "unknown"),
        "external_data_transfer": processing.get("external_data_transfer", "no" if llm_mode == "private_only" else "unknown"),
        "private_processing_required": bool(document.metadata.get("external_processing_allowed") is False),
    }


def _delete_managed_file(path: Path, managed_root: Path) -> dict[str, Any]:
    try:
        resolved_root = managed_root.resolve()
        resolved_path = path.resolve()
        if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
            return {"status": "skipped", "reason": "outside_managed_root"}
        if resolved_path.exists() and resolved_path.is_file():
            size = resolved_path.stat().st_size
            resolved_path.unlink()
            return {"status": "deleted", "bytes": size}
        return {"status": "not_found"}
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}


def temporary_expiry(value: str | None) -> datetime | None:
    if not value:
        return None
    now = datetime.utcnow()
    normalized = value.strip().lower()
    if normalized in {"session", "delete_after_session"}:
        return now
    if normalized in {"1h", "1 hour"}:
        return now + timedelta(hours=1)
    if normalized in {"24h", "24 hours", "1 day"}:
        return now + timedelta(days=1)
    if normalized in {"7d", "7 days"}:
        return now + timedelta(days=7)
    if normalized in {"30d", "30 days"}:
        return now + timedelta(days=30)
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
