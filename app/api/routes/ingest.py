from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from app.api.auth_context import get_current_user
from app.api.rbac import require_permission
from app.core.dependencies import get_app_settings, get_indexer, get_metadata_store, get_query_cache, get_redis_service, get_worker_queue
from app.core.schemas import IngestionJobRecord, IngestResponse, TextSourceRequest, UserRecord

router = APIRouter(prefix="/ingest", tags=["ingest"])
public_router = APIRouter(tags=["sources"])
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".txt", ".md", ".docx", ".csv", ".xlsx", ".pptx"}
IMAGE_SIGNATURES = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".webp": (b"RIFF",),
    ".bmp": (b"BM",),
    ".tiff": (b"II*\x00", b"MM\x00*"),
}


@router.post("/pdf", response_model=list[IngestResponse])
async def ingest_pdf(
    files: list[UploadFile] = File(...),
    indexer=Depends(get_indexer),
    metadata_store=Depends(get_metadata_store),
    settings=Depends(get_app_settings),
) -> list[IngestResponse]:
    _validate_file_count(files, settings.max_upload_files)
    _validate_workspace_quota("default", len(files), metadata_store, settings)
    responses: list[IngestResponse] = []
    for upload in files:
        filename = Path(upload.filename or "source").name
        suffix = _validate_extension(filename)
        destination = Path(settings.upload_dir) / filename
        await _save_validated_upload(upload, destination, suffix, settings.max_upload_bytes)
        responses.append(indexer.ingest_pdf(destination))
    return responses


@public_router.post("/workspaces/{workspace_id}/sources", response_model=list[IngestionJobRecord], status_code=202)
async def upload_workspace_sources(
    workspace_id: str,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    objective_profile: str = Form(default="general"),
    indexer=Depends(get_indexer),
    metadata_store=Depends(get_metadata_store),
    redis_service=Depends(get_redis_service),
    query_cache=Depends(get_query_cache),
    worker_queue=Depends(get_worker_queue),
    settings=Depends(get_app_settings),
    user: UserRecord = Depends(get_current_user),
) -> list[IngestionJobRecord]:
    workspace = require_permission(workspace_id, "document.upload", user, metadata_store)
    _validate_file_count(files, settings.max_upload_files)
    _validate_workspace_quota(workspace_id, len(files), metadata_store, settings)
    jobs: list[IngestionJobRecord] = []
    workspace_dir = Path(settings.upload_dir) / "tenants" / workspace.tenant_id / "workspaces" / workspace_id / "documents"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    for upload in files:
        filename = Path(upload.filename or "source").name
        suffix = _validate_extension(filename)
        destination_dir = workspace_dir / str(uuid.uuid4())
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / filename
        await _save_validated_upload(upload, destination, suffix, settings.max_upload_bytes)
        job = _new_job(workspace_id, filename, {"source_path": str(destination), "objective_profile": objective_profile, "tenant_id": workspace.tenant_id})
        metadata_store.upsert_ingestion_job(job)
        _mirror_job_progress(redis_service, job)
        jobs.append(job)
        if settings.enable_queue_ingestion:
            _enqueue_ingestion_job(worker_queue, job, destination, objective_profile, metadata_store, redis_service)
        else:
            background_tasks.add_task(_process_ingestion_job, job, destination, indexer, metadata_store, objective_profile, redis_service, query_cache)
    return jobs


@public_router.post("/workspaces/{workspace_id}/sources/text", response_model=IngestionJobRecord, status_code=202)
def add_text_source(
    workspace_id: str,
    request: TextSourceRequest,
    background_tasks: BackgroundTasks,
    indexer=Depends(get_indexer),
    metadata_store=Depends(get_metadata_store),
    redis_service=Depends(get_redis_service),
    query_cache=Depends(get_query_cache),
    worker_queue=Depends(get_worker_queue),
    settings=Depends(get_app_settings),
    user: UserRecord = Depends(get_current_user),
) -> IngestionJobRecord:
    workspace = require_permission(workspace_id, "document.upload", user, metadata_store)
    _validate_workspace_quota(workspace_id, 1, metadata_store, settings)
    if len(request.text) > settings.max_pasted_text_chars:
        raise HTTPException(status_code=413, detail=f"Pasted text exceeds {settings.max_pasted_text_chars} characters.")
    destination_dir = Path(settings.upload_dir) / "tenants" / workspace.tenant_id / "workspaces" / workspace_id / "documents" / str(uuid.uuid4())
    destination_dir.mkdir(parents=True, exist_ok=True)
    safe_title = Path(request.title).stem.strip() or "Pasted Notes"
    destination = destination_dir / f"{safe_title}.md"
    destination.write_text(request.text, encoding="utf-8")
    source_metadata = {
        "source_path": str(destination),
        "source_kind": request.metadata.get("source_type", "pasted_text"),
        "tenant_id": workspace.tenant_id,
        **request.metadata,
    }
    job = _new_job(workspace_id, destination.name, source_metadata)
    metadata_store.upsert_ingestion_job(job)
    _mirror_job_progress(redis_service, job)
    if settings.enable_queue_ingestion:
        _enqueue_ingestion_job(worker_queue, job, destination, "general", metadata_store, redis_service)
    else:
        background_tasks.add_task(_process_ingestion_job, job, destination, indexer, metadata_store, "general", redis_service, query_cache)
    return job


@public_router.get("/ingestions/{job_id}", response_model=IngestionJobRecord)
def get_ingestion_job(
    job_id: str,
    metadata_store=Depends(get_metadata_store),
    redis_service=Depends(get_redis_service),
    user: UserRecord = Depends(get_current_user),
) -> IngestionJobRecord:
    job = metadata_store.get_ingestion_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found.")
    require_permission(job.workspace_id, "workspace.read", user, metadata_store)
    return _job_with_redis_progress(job, redis_service)


@public_router.post("/ingestions/{job_id}/retry", response_model=IngestionJobRecord, status_code=202)
def retry_ingestion_job(
    job_id: str,
    metadata_store=Depends(get_metadata_store),
    redis_service=Depends(get_redis_service),
    worker_queue=Depends(get_worker_queue),
    user: UserRecord = Depends(get_current_user),
) -> IngestionJobRecord:
    job = metadata_store.get_ingestion_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found.")
    require_permission(job.workspace_id, "document.upload", user, metadata_store)
    source_path = job.metadata.get("source_path")
    if not source_path:
        raise HTTPException(status_code=400, detail="Ingestion job cannot be retried because source_path is missing.")
    job.status = "uploaded"
    job.progress = 0
    job.message = "Retry queued for background indexing."
    job.updated_at = datetime.utcnow()
    job.metadata = {**job.metadata, "retry_requested_at": job.updated_at.isoformat(), "retry_requested_by": user.user_id}
    metadata_store.upsert_ingestion_job(job)
    _mirror_job_progress(redis_service, job)
    worker_queue.enqueue(
        "ingestion",
        {
            "ingestion_job_id": job.job_id,
            "workspace_id": job.workspace_id,
            "source_path": source_path,
            "objective_profile": job.metadata.get("objective_profile", "general"),
        },
        job_id=job.job_id,
    )
    return job


def _new_job(workspace_id: str, filename: str, metadata: dict) -> IngestionJobRecord:
    now = datetime.utcnow()
    return IngestionJobRecord(
        job_id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        filename=filename,
        status="uploaded",
        progress=0,
        created_at=now,
        updated_at=now,
        metadata=metadata,
    )


def _validate_file_count(files: list[UploadFile], max_files: int) -> None:
    if not files:
        raise HTTPException(status_code=400, detail="Choose at least one source file.")
    if len(files) > max_files:
        raise HTTPException(status_code=413, detail=f"Upload limit is {max_files} files at a time.")


def _validate_workspace_quota(workspace_id: str, incoming_count: int, metadata_store, settings) -> None:
    current_count = len(metadata_store.list_documents(workspace_id=workspace_id))
    if current_count + incoming_count > settings.max_workspace_documents:
        raise HTTPException(
            status_code=403,
            detail=f"Free workspace document quota reached: {current_count}/{settings.max_workspace_documents}.",
        )


def _validate_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported source type: {suffix or 'unknown'}")
    return suffix


async def _save_validated_upload(upload: UploadFile, destination: Path, suffix: str, max_bytes: int) -> None:
    total = 0
    first_chunk = b""
    try:
        with destination.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                if not first_chunk:
                    first_chunk = chunk
                    _validate_signature(first_chunk, suffix)
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail=f"File exceeds upload limit of {max_bytes // (1024 * 1024)} MB.")
                handle.write(chunk)
    except Exception:
        if destination.exists():
            destination.unlink()
        raise
    if total == 0:
        if destination.exists():
            destination.unlink()
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")


def _validate_signature(first_chunk: bytes, suffix: str) -> None:
    if suffix == ".pdf" and not first_chunk.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="Uploaded file does not look like a valid PDF.")
    if suffix in IMAGE_SIGNATURES and not any(first_chunk.startswith(signature) for signature in IMAGE_SIGNATURES[suffix]):
        raise HTTPException(status_code=415, detail=f"Uploaded file does not look like a valid {suffix} image.")
    if suffix in {".txt", ".md"}:
        try:
            first_chunk[:4096].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="Text uploads must be UTF-8 compatible.") from exc
    if suffix in {".docx", ".xlsx", ".pptx"} and not first_chunk.startswith(b"PK"):
        raise HTTPException(status_code=415, detail=f"Uploaded file does not look like a valid {suffix.upper()[1:]} document.")
    if suffix == ".csv":
        try:
            first_chunk[:4096].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="CSV uploads must be UTF-8 compatible.") from exc


def _process_ingestion_job(job: IngestionJobRecord, destination: Path, indexer, metadata_store, objective_profile: str = "general", redis_service=None, query_cache=None) -> None:
    def report(status: str, progress: int, message: str) -> None:
        job.status = status
        job.progress = progress
        job.message = message
        job.updated_at = datetime.utcnow()
        _mirror_job_progress(redis_service, job)
        metadata_store.upsert_ingestion_job(job)

    try:
        try:
            response = indexer.ingest_source(destination, workspace_id=job.workspace_id, progress_callback=report, objective_profile=objective_profile)
        except TypeError as exc:
            if "objective_profile" not in str(exc):
                raise
            response = indexer.ingest_source(destination, workspace_id=job.workspace_id, progress_callback=report)
        job.document_id = response.document.document_id
        job.status = "ready"
        job.progress = 100
        job.message = "Source is ready for chat."
        _invalidate_retrieval_cache(query_cache, metadata_store, job.workspace_id)
    except Exception as exc:
        job.status = "failed"
        job.message = str(exc)
    job.updated_at = datetime.utcnow()
    _mirror_job_progress(redis_service, job)
    metadata_store.upsert_ingestion_job(job)


def _enqueue_ingestion_job(worker_queue, job: IngestionJobRecord, destination: Path, objective_profile: str, metadata_store, redis_service=None) -> None:
    job.status = "uploaded"
    job.message = "Queued for background indexing."
    job.updated_at = datetime.utcnow()
    metadata_store.upsert_ingestion_job(job)
    _mirror_job_progress(redis_service, job)
    worker_queue.enqueue(
        "ingestion",
        {
            "ingestion_job_id": job.job_id,
            "workspace_id": job.workspace_id,
            "source_path": str(destination),
            "objective_profile": objective_profile,
        },
        job_id=job.job_id,
    )


def _invalidate_retrieval_cache(query_cache, metadata_store, workspace_id: str) -> None:
    if query_cache is None:
        return
    workspace = metadata_store.get_workspace(workspace_id) if hasattr(metadata_store, "get_workspace") else None
    tenant_id = workspace.tenant_id if workspace is not None else "default-tenant"
    query_cache.invalidate_workspace(tenant_id=tenant_id, workspace_id=workspace_id)


def _mirror_job_progress(redis_service, job: IngestionJobRecord) -> None:
    if redis_service is None:
        return
    payload = {
        "job_id": job.job_id,
        "workspace_id": job.workspace_id,
        "filename": job.filename,
        "status": job.status,
        "progress": job.progress,
        "document_id": job.document_id,
        "message": job.message,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }
    try:
        redis_service.set_ingestion_progress(job.job_id, payload, tenant_id=job.metadata.get("tenant_id"), workspace_id=job.workspace_id)
    except TypeError:
        redis_service.set_ingestion_progress(job.job_id, payload)


def _job_with_redis_progress(job: IngestionJobRecord, redis_service) -> IngestionJobRecord:
    if redis_service is None:
        return job
    try:
        progress = redis_service.get_ingestion_progress(job.job_id, tenant_id=job.metadata.get("tenant_id"), workspace_id=job.workspace_id)
    except TypeError:
        progress = redis_service.get_ingestion_progress(job.job_id)
    if not progress:
        return job
    return job.model_copy(
        update={
            "status": progress.get("status", job.status),
            "progress": int(progress.get("progress", job.progress) or 0),
            "document_id": progress.get("document_id") or job.document_id,
            "message": progress.get("message", job.message),
        }
    )
