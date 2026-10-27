from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth_context import get_current_user
from app.api.rbac import require_permission
from app.core.dependencies import get_app_settings, get_metadata_store, get_redis_service, get_worker_queue
from app.core.schemas import BrowserCaptureRequest, BrowserPageQueryRequest, BrowserSummaryResponse, IngestionJobRecord, UserRecord

router = APIRouter(prefix="/browser", tags=["browser-extension"])


@router.post("/capture", response_model=IngestionJobRecord, status_code=202)
def capture_browser_page(
    request: BrowserCaptureRequest,
    settings=Depends(get_app_settings),
    metadata_store=Depends(get_metadata_store),
    redis_service=Depends(get_redis_service),
    worker_queue=Depends(get_worker_queue),
    user: UserRecord = Depends(get_current_user),
) -> IngestionJobRecord:
    workspace = require_permission(request.workspace_id, "document.upload", user, metadata_store)
    if len(request.text) > settings.max_pasted_text_chars:
        raise HTTPException(status_code=413, detail=f"Captured page exceeds {settings.max_pasted_text_chars} characters.")
    source_hash = _source_hash(request.url, request.text)
    destination_dir = Path(settings.upload_dir) / "tenants" / workspace.tenant_id / "workspaces" / request.workspace_id / "browser" / str(uuid.uuid4())
    destination_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_safe_title(request.title)}.md"
    destination = destination_dir / filename
    destination.write_text(f"# {request.title}\n\nSource: {request.url}\n\n{_sanitize_capture_text(request.text)}", encoding="utf-8")
    now = datetime.utcnow()
    job = IngestionJobRecord(
        job_id=str(uuid.uuid4()),
        workspace_id=request.workspace_id,
        filename=filename,
        status="uploaded",
        progress=0,
        message="Browser page queued for indexing.",
        created_at=now,
        updated_at=now,
        metadata={
            "source_path": str(destination),
            "tenant_id": workspace.tenant_id,
            "source_kind": "browser_page",
            "source_type": "browser_page",
            "original_url": request.url,
            "title": request.title,
            "selection_used": request.selection_used,
            "captured_at": now.isoformat(),
            "extension_version": request.extension_version,
            "source_hash": source_hash,
            **request.metadata,
        },
    )
    metadata_store.upsert_ingestion_job(job)
    if redis_service is not None:
        redis_service.set_ingestion_progress(job.job_id, job.model_dump(mode="json"), tenant_id=workspace.tenant_id, workspace_id=request.workspace_id)
    worker_queue.enqueue("ingestion", {"ingestion_job_id": job.job_id, "workspace_id": request.workspace_id, "source_path": str(destination), "objective_profile": "general"}, job_id=job.job_id)
    metadata_store.add_audit_log("browser.capture", user=user, workspace_id=request.workspace_id, resource_type="browser_page", resource_id=job.job_id, metadata={"url": request.url, "source_hash": source_hash})
    return job


@router.post("/summarize", response_model=BrowserSummaryResponse)
def summarize_browser_page(
    request: BrowserCaptureRequest,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> BrowserSummaryResponse:
    require_permission(request.workspace_id, "document.query", user, metadata_store)
    cleaned = _sanitize_capture_text(request.text)
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", cleaned) if len(sentence.strip()) > 20]
    summary = " ".join(sentences[:3]) or cleaned[:500]
    entities = _extract_entities(cleaned)
    return BrowserSummaryResponse(title=request.title, url=request.url, summary=summary[:1200], entities=entities, source_hash=_source_hash(request.url, request.text))


@router.post("/entities", response_model=dict)
def browser_page_entities(
    request: BrowserCaptureRequest,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> dict:
    require_permission(request.workspace_id, "document.query", user, metadata_store)
    return {"entities": _extract_entities(_sanitize_capture_text(request.text)), "source_hash": _source_hash(request.url, request.text)}


@router.post("/current-page/query", response_model=BrowserSummaryResponse)
def ask_current_browser_page(
    request: BrowserPageQueryRequest,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> BrowserSummaryResponse:
    require_permission(request.workspace_id, "document.query", user, metadata_store)
    cleaned = _sanitize_capture_text(request.text)
    terms = [term.lower() for term in re.findall(r"\w{4,}", request.question)]
    matching = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", cleaned) if any(term in sentence.lower() for term in terms)]
    answer = " ".join(matching[:4]) or "No direct evidence from the current page matched the question."
    return BrowserSummaryResponse(title=request.title, url=request.url, summary=answer[:1200], entities=_extract_entities(cleaned), source_hash=_source_hash(request.url, request.text))


def _sanitize_capture_text(text: str) -> str:
    text = re.sub(r"(?i)(password|token|secret|api[_ -]?key)\s*[:=]\s*\S+", r"\1: [redacted]", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _extract_entities(text: str) -> list[str]:
    candidates = re.findall(r"\b[A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]+){0,3}\b", text)
    ignored = {"The", "This", "That", "Source", "Page", "Browser Page"}
    entities = []
    for candidate in candidates:
        if candidate not in ignored and candidate not in entities:
            entities.append(candidate)
    return entities[:20]


def _source_hash(url: str, text: str) -> str:
    return hashlib.sha256(f"{url}\n{text[:10000]}".encode("utf-8")).hexdigest()


def _safe_title(title: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_. -]+", "", title).strip()[:80]
    return cleaned or "Browser Page"
