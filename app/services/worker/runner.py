from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.worker.queue import WorkerJob, WorkerQueue


class AiwanaWorker:
    def __init__(self, *, queue: WorkerQueue, indexer=None, metadata_store=None, redis_service=None, query_cache=None) -> None:
        self.queue = queue
        self.indexer = indexer
        self.metadata_store = metadata_store
        self.redis_service = redis_service
        self.query_cache = query_cache
        self.last_heartbeat: str | None = None
        self.last_error: str | None = None

    def heartbeat(self) -> dict[str, Any]:
        self.last_heartbeat = datetime.utcnow().isoformat()
        payload = {"status": "ok", "heartbeat_at": self.last_heartbeat, **self.queue.status(), "last_error": self.last_error}
        if self.redis_service is not None:
            self.redis_service.set_json("aiwana:worker:heartbeat", payload, ttl_seconds=120)
        return payload

    def process_one(self) -> dict[str, Any]:
        self.heartbeat()
        job = self.queue.dequeue()
        if job is None:
            return {"status": "idle", **self.queue.status()}
        try:
            result = self._process(job)
            return {"status": "processed", "job_id": job.job_id, "job_type": job.job_type, "result": result}
        except Exception as exc:
            self.last_error = str(exc)
            self.queue.requeue(job)
            self._mark_failed(job, str(exc))
            return {"status": "retrying" if job.attempts < job.max_attempts else "failed", "job_id": job.job_id, "error": str(exc)}

    def _process(self, job: WorkerJob) -> dict[str, Any]:
        if job.job_type in {"ingestion", "ocr", "embedding", "artifact_preview"}:
            return self._process_ingestion(job)
        raise ValueError(f"Unsupported worker job type: {job.job_type}")

    def _process_ingestion(self, job: WorkerJob) -> dict[str, Any]:
        if self.indexer is None or self.metadata_store is None:
            return {"skipped": True, "reason": "indexer_or_metadata_store_unavailable"}
        source_path = Path(job.payload["source_path"])
        ingestion_job_id = job.payload.get("ingestion_job_id")
        objective_profile = job.payload.get("objective_profile", "general")
        if ingestion_job_id:
            existing = self.metadata_store.get_ingestion_job(ingestion_job_id)
            if existing and existing.status == "ready":
                return {"idempotent": True, "document_id": existing.document_id}
        self._mark_progress(job, "processing", 5, "Worker started indexing.")

        def report(status: str, progress: int, message: str) -> None:
            self._mark_progress(job, status, progress, message)

        result = self.indexer.ingest_source(
            source_path,
            workspace_id=job.payload.get("workspace_id", "default"),
            objective_profile=objective_profile,
            progress_callback=report,
        )
        self._invalidate_retrieval_cache(job)
        self._mark_ready(job, result.document.document_id)
        return {"document_id": result.document.document_id, "chunks_created": result.chunks_created}

    def _invalidate_retrieval_cache(self, job: WorkerJob) -> None:
        if self.query_cache is None or self.metadata_store is None:
            return
        workspace_id = job.payload.get("workspace_id", "default")
        tenant_id = "default-tenant"
        workspace = self.metadata_store.get_workspace(workspace_id) if hasattr(self.metadata_store, "get_workspace") else None
        if workspace is not None:
            tenant_id = workspace.tenant_id
        self.query_cache.invalidate_workspace(tenant_id=tenant_id, workspace_id=workspace_id)

    def _mark_progress(self, job: WorkerJob, status: str, progress: int, message: str) -> None:
        ingestion_job_id = job.payload.get("ingestion_job_id")
        if not ingestion_job_id or self.metadata_store is None:
            return
        record = self.metadata_store.get_ingestion_job(ingestion_job_id)
        if record is None:
            return
        record.status = status
        record.progress = progress
        record.message = message
        record.updated_at = datetime.utcnow()
        record.metadata = {**record.metadata, "worker_attempts": job.attempts, "worker_job_type": job.job_type}
        self.metadata_store.upsert_ingestion_job(record)
        if self.redis_service is not None:
            self.redis_service.set_ingestion_progress(record.job_id, record.model_dump(mode="json"))

    def _mark_ready(self, job: WorkerJob, document_id: str) -> None:
        ingestion_job_id = job.payload.get("ingestion_job_id")
        if not ingestion_job_id or self.metadata_store is None:
            return
        record = self.metadata_store.get_ingestion_job(ingestion_job_id)
        if record is None:
            return
        record.status = "ready"
        record.progress = 100
        record.document_id = document_id
        record.message = "Source is ready for chat."
        record.updated_at = datetime.utcnow()
        self.metadata_store.upsert_ingestion_job(record)
        if self.redis_service is not None:
            self.redis_service.set_ingestion_progress(record.job_id, record.model_dump(mode="json"))

    def _mark_failed(self, job: WorkerJob, message: str) -> None:
        ingestion_job_id = job.payload.get("ingestion_job_id")
        if not ingestion_job_id or self.metadata_store is None:
            return
        record = self.metadata_store.get_ingestion_job(ingestion_job_id)
        if record is None:
            return
        record.status = "failed"
        record.message = message
        record.metadata = {**record.metadata, "worker_attempts": job.attempts, "last_worker_error": message}
        self.metadata_store.upsert_ingestion_job(record)
