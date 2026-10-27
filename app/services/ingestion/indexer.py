from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path

from app.core.config import get_settings
from app.core.schemas import DocumentRecord, EvidenceAnchorRecord, ExtractedArtifact, IngestResponse, MemoryRecord


class DocumentIndexer:
    INDEXING_VERSION = "indexer-v3"

    def __init__(self, parser, chunker, embedder, vector_store, sparse_store, metadata_store, graph_repository=None) -> None:
        self.parser = parser
        self.chunker = chunker
        self.embedder = embedder
        self.vector_store = vector_store
        self.sparse_store = sparse_store
        self.metadata_store = metadata_store
        self.graph_repository = graph_repository

    def ingest_pdf(
        self,
        file_path: str | Path,
        workspace_id: str = "default",
        progress_callback=None,
        objective_profile: str = "general",
        force_reindex: bool = False,
    ) -> IngestResponse:
        return self.ingest_source(
            file_path,
            workspace_id=workspace_id,
            progress_callback=progress_callback,
            objective_profile=objective_profile,
            force_reindex=force_reindex,
        )

    def ingest_source(
        self,
        file_path: str | Path,
        workspace_id: str = "default",
        progress_callback=None,
        objective_profile: str = "general",
        force_reindex: bool = False,
    ) -> IngestResponse:
        path = Path(file_path)
        settings = get_settings()
        fingerprint = self._fingerprint_file(path)
        existing = self.metadata_store.get_document_by_fingerprint(fingerprint, workspace_id=workspace_id)
        existing_version = (existing.metadata or {}).get("indexing_version") if existing else None
        current_version = f"{self.INDEXING_VERSION}:{getattr(self.parser, 'PARSER_VERSION', 'parser-v1')}"
        if (
            not force_reindex
            and existing
            and existing.status == "indexed"
            and self.metadata_store.has_chunks_for_document(existing.document_id)
            and existing_version == current_version
        ):
            return IngestResponse(document=existing, chunks_created=len(self.metadata_store.list_chunks(existing.document_id)), indexed=True, duplicate=True)

        self._report_progress(progress_callback, "parsing", 20, "Parsing source content.")
        record = existing or DocumentRecord(
            document_id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            filename=path.name,
            source_path=str(path),
            fingerprint=fingerprint,
            status="processing",
            page_count=0,
            ingested_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            metadata={"multimodal_ready": True, "page_asset_refs": [], "indexing_version": current_version, "source_type": path.suffix.lower(), "objective_profile": objective_profile},
        )
        record.workspace_id = workspace_id
        record.filename = path.name
        record.source_path = str(path)
        record.fingerprint = fingerprint
        record.status = "processing"
        record.updated_at = datetime.utcnow()
        record.metadata = {**record.metadata, "indexing_version": current_version, "objective_profile": objective_profile}
        if record.metadata.get("external_processing_allowed") is False and _provider_is_external(settings.embedding_provider):
            record.status = "failed"
            record.metadata = {**record.metadata, "error": "Private embedding provider unavailable for external-processing-disabled document."}
            self.metadata_store.upsert_document(record)
            raise RuntimeError("Private embedding provider unavailable for external-processing-disabled document.")
        self.metadata_store.upsert_document(record)

        chunk_ids: list[str] = []
        try:
            if existing and self.metadata_store.has_chunks_for_document(record.document_id):
                existing_chunks = self.metadata_store.list_chunks(record.document_id)
                existing_chunk_ids = [chunk.chunk_id for chunk in existing_chunks]
                self.vector_store.delete(existing_chunk_ids)
                self.sparse_store.remove_documents(existing_chunk_ids)
                self.metadata_store.delete_chunks(existing_chunk_ids)
            pages = self.parser.parse(path)
            self._report_progress(progress_callback, "extracting_visuals", 50, "Extracting page and visual evidence.")
            record.page_count = len(pages)
            try:
                chunks = self.chunker.split_document(document_id=record.document_id, filename=path.name, pages=pages, workspace_id=workspace_id)
            except TypeError as exc:
                if "workspace_id" not in str(exc):
                    raise
                chunks = self.chunker.split_document(document_id=record.document_id, filename=path.name, pages=pages)
                for chunk in chunks:
                    chunk.workspace_id = workspace_id
            for chunk in chunks:
                chunk.metadata = {
                    **chunk.metadata,
                    "document_mode": record.metadata.get("document_mode", "knowledge_base"),
                    "classification": record.metadata.get("classification", "internal"),
                    "external_processing_allowed": record.metadata.get("external_processing_allowed", True),
                    "processing_metadata": {
                        "embedding_provider": settings.embedding_provider,
                        "embedding_model": settings.embedding_model,
                        "ocr_provider": "local_worker" if settings.enable_multimodal else "disabled",
                    },
                }
            self._report_progress(progress_callback, "embedding", 70, "Indexing searchable evidence.")
            vectors = self.embedder.embed_documents([chunk.text for chunk in chunks]) if chunks else []
            sparse_vectors = self._sparse_vectors_for_chunks([chunk.text for chunk in chunks]) if chunks else []
            workspace = self.metadata_store.get_workspace(workspace_id)
            payloads = [
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "workspace_id": workspace_id,
                    "tenant_id": workspace.tenant_id if workspace else "default-tenant",
                    "filename": chunk.filename,
                    "page_number": chunk.page_number,
                    "content_type": chunk.content_type or chunk.metadata.get("content_type", "text"),
                    "objective_profile": record.metadata.get("objective_profile", "general"),
                }
                for chunk in chunks
            ]
            chunk_ids = [chunk.chunk_id for chunk in chunks]
            if chunks and vectors:
                self.vector_store.upsert(chunk_ids, vectors, payloads, sparse_vectors=sparse_vectors or None)
                self.sparse_store.upsert_documents({chunk.chunk_id: chunk.text for chunk in chunks})
                self.metadata_store.insert_chunks(chunks)
                self._store_chunk_evidence_anchors(chunks)
            record.status = "indexed"
            record.updated_at = datetime.utcnow()
            record.metadata = {
                "multimodal_ready": True,
                "indexing_version": current_version,
                "source_type": path.suffix.lower(),
                "objective_profile": objective_profile,
                "document_mode": record.metadata.get("document_mode", "knowledge_base"),
                "classification": record.metadata.get("classification", "internal"),
                "expires_at": record.metadata.get("expires_at"),
                "retention_days": record.metadata.get("retention_days"),
                "external_processing_allowed": record.metadata.get("external_processing_allowed", True),
                "processing_metadata": {
                    "embedding_provider": settings.embedding_provider,
                    "embedding_model": settings.embedding_model,
                    "ocr_provider": "local_worker" if settings.enable_multimodal else "disabled",
                    "llm_provider": settings.llm_provider,
                    "external_data_transfer": "yes" if _provider_is_external(settings.embedding_provider) or _provider_is_external(settings.llm_provider) else "no",
                    "indexed_at": datetime.utcnow().isoformat(),
                },
                "page_asset_refs": [
                    {
                        "page_number": page["page_number"],
                        "has_images": page["metadata"].get("has_images", False),
                        "tables": page["metadata"].get("tables", []),
                        "charts": page["metadata"].get("charts", []),
                        "clauses": page["metadata"].get("clauses", []),
                        "risks": page["metadata"].get("risks", []),
                        "definitions": page["metadata"].get("definitions", []),
                        "figures": page["metadata"].get("figures", []),
                        "visual_assets": page["metadata"].get("visual_assets", []),
                        "source_anchors": page["metadata"].get("source_anchors", []),
                        "preview_path": page["metadata"].get("preview_path"),
                    }
                    for page in pages
                ],
            }
            self._store_page_artifacts(record.document_id, workspace_id, pages)
            self._store_document_memory(record.document_id, workspace_id, record.filename, objective_profile, pages)
            self._store_graph_memory(record.document_id, workspace_id, record.filename, pages)
            self.metadata_store.upsert_document(record)
            self._report_progress(progress_callback, "ready", 100, "Source is ready for chat.")
            return IngestResponse(document=record, chunks_created=len(chunks), indexed=bool(chunks), duplicate=False)
        except Exception as exc:
            if chunk_ids:
                self.vector_store.delete(chunk_ids)
                self.sparse_store.remove_documents(chunk_ids)
                self.metadata_store.delete_chunks(chunk_ids)
            record.status = "failed"
            record.updated_at = datetime.utcnow()
            record.metadata = {
                **record.metadata,
                "error": str(exc),
            }
            self.metadata_store.upsert_document(record)
            raise

    @staticmethod
    def _report_progress(callback, status: str, progress: int, message: str) -> None:
        if callback:
            callback(status, progress, message)

    @staticmethod
    def _fingerprint_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _sparse_vectors_for_chunks(self, texts: list[str]) -> list[dict[int, float]]:
        if not texts:
            return []
        pop_cached = getattr(self.embedder, "pop_last_sparse_vectors", None)
        if callable(pop_cached):
            cached = pop_cached()
            if len(cached) == len(texts):
                return cached
        embed_sparse = getattr(self.embedder, "embed_sparse_documents", None)
        if callable(embed_sparse):
            return embed_sparse(texts)
        return []

    def _store_page_artifacts(self, document_id: str, workspace_id: str, pages: list[dict]) -> None:
        for page in pages:
            metadata = page.get("metadata", {})
            for table in metadata.get("tables", []) or []:
                self._store_artifact(document_id, workspace_id, page["page_number"], "table", table)
            for chart in metadata.get("charts", []) or []:
                self._store_artifact(document_id, workspace_id, page["page_number"], "chart", chart)
            for clause in metadata.get("clauses", []) or []:
                self._store_artifact(document_id, workspace_id, page["page_number"], "clause", clause)
            for risk in metadata.get("risks", []) or []:
                self._store_artifact(document_id, workspace_id, page["page_number"], "risk", risk)
            for definition in metadata.get("definitions", []) or []:
                self._store_artifact(document_id, workspace_id, page["page_number"], "definition", definition)
            if metadata.get("section_path"):
                section = {
                    "artifact_id": str(uuid.uuid4()),
                    "title": " > ".join(metadata["section_path"]),
                    "text": page.get("text", "")[:1000],
                    "section_path": metadata["section_path"],
                }
                self._store_artifact(document_id, workspace_id, page["page_number"], "section", section)
            for figure in metadata.get("figures", []) or []:
                self._store_artifact(document_id, workspace_id, page["page_number"], "figure", figure)

    def _store_artifact(self, document_id: str, workspace_id: str, page_number: int, artifact_type: str, payload: dict) -> None:
        artifact_id = payload.get("artifact_id") or payload.get("anchor_id") or str(uuid.uuid4())
        self.metadata_store.upsert_extracted_artifact(
            ExtractedArtifact(
                artifact_id=artifact_id,
                document_id=document_id,
                workspace_id=workspace_id,
                artifact_type=artifact_type,
                page_number=page_number,
                title=payload.get("title"),
                text=payload.get("text") or payload.get("caption", ""),
                data=payload,
                bbox=payload.get("bbox"),
                created_at=datetime.utcnow(),
            )
        )
        self.metadata_store.upsert_evidence_anchor(
            EvidenceAnchorRecord(
                anchor_id=artifact_id,
                document_id=document_id,
                workspace_id=workspace_id,
                artifact_id=artifact_id,
                anchor_type=artifact_type if artifact_type in {"figure", "table", "chart", "clause", "risk", "definition"} else "artifact",
                page_number=page_number,
                bbox=payload.get("bbox"),
                preview_path=payload.get("preview_path"),
                crop_path=payload.get("crop_path"),
                citation_text=payload.get("text") or payload.get("caption") or payload.get("title") or "",
                metadata=payload,
                created_at=datetime.utcnow(),
            )
        )

    def _store_chunk_evidence_anchors(self, chunks) -> None:
        for chunk in chunks:
            page_metadata = chunk.metadata.get("page_metadata", {}) if chunk.metadata else {}
            self.metadata_store.upsert_evidence_anchor(
                EvidenceAnchorRecord(
                    anchor_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    workspace_id=chunk.workspace_id,
                    chunk_id=chunk.chunk_id,
                    anchor_type="chunk",
                    page_number=chunk.page_number,
                    bbox=chunk.bbox,
                    preview_path=page_metadata.get("preview_path"),
                    crop_path=None,
                    citation_text=chunk.text[:1000],
                    metadata={
                        "filename": chunk.filename,
                        "content_type": chunk.content_type,
                        "section_path": chunk.section_path,
                        "risk_tags": chunk.risk_tags,
                    },
                    created_at=datetime.utcnow(),
                )
            )

    def _store_document_memory(self, document_id: str, workspace_id: str, filename: str, objective_profile: str, pages: list[dict]) -> None:
        sections: list[str] = []
        risks: list[str] = []
        definitions: list[str] = []
        tables = 0
        charts = 0
        figures = 0
        for page in pages:
            metadata = page.get("metadata", {})
            sections.extend(" > ".join(metadata.get("section_path", [])) for _ in [0] if metadata.get("section_path"))
            risks.extend(risk.get("title") or risk.get("tag", "") for risk in metadata.get("risks", []) if risk.get("title") or risk.get("tag"))
            definitions.extend(item.get("title", "") for item in metadata.get("definitions", []) if item.get("title"))
            tables += len(metadata.get("tables", []) or [])
            charts += len(metadata.get("charts", []) or [])
            figures += len(metadata.get("figures", []) or [])
        summary = (
            f"Document {filename}: {len(pages)} page(s), {tables} table(s), {charts} chart(s), "
            f"{figures} figure/image anchor(s), risks: {', '.join(sorted(set(risks))[:8]) or 'none detected'}."
        )
        entities = sorted({*sections[:12], *risks[:12], *definitions[:12]})
        self.metadata_store.upsert_memory(
            MemoryRecord(
                memory_id=f"document:{document_id}",
                session_id=f"document:{document_id}",
                workspace_id=workspace_id,
                user_id="system",
                objective_profile=objective_profile if objective_profile in {"general", "legal", "research", "enterprise"} else "general",
                memory_type="document",
                content=summary,
                entities=[entity for entity in entities if entity],
                metadata={
                    "document_id": document_id,
                    "filename": filename,
                    "page_count": len(pages),
                    "table_count": tables,
                    "chart_count": charts,
                    "figure_count": figures,
                    "sections": sorted(set(sections))[:24],
                    "risk_topics": sorted(set(risks))[:24],
                    "definitions": sorted(set(definitions))[:24],
                },
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )

    def _store_graph_memory(self, document_id: str, workspace_id: str, filename: str, pages: list[dict]) -> None:
        if self.graph_repository is None or not getattr(self.graph_repository, "enabled", False):
            return
        workspace = self.metadata_store.get_workspace(workspace_id)
        tenant_id = workspace.tenant_id if workspace else "default-tenant"
        result = self.graph_repository.index_document_graph(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            document_id=document_id,
            filename=filename,
            pages=pages,
        )
        document_memory = self.metadata_store.list_workspace_memory(workspace_id, memory_type="document", limit=1)
        if document_memory:
            for fact in self.graph_repository.search_graph(filename, tenant_id=tenant_id, workspace_id=workspace_id, limit=8):
                self.graph_repository.link_memory_entity(
                    memory_id=document_memory[0].memory_id,
                    entity_id=fact.source.entity_id,
                    confidence=fact.source.confidence,
                )
        if result:
            self.metadata_store.add_audit_log(
                "graph.index_document",
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                resource_type="document",
                resource_id=document_id,
                metadata=result,
            )


def _provider_is_external(provider: str | None) -> bool:
    return str(provider or "").lower() in {"openai", "groq", "anthropic", "public", "external"}
