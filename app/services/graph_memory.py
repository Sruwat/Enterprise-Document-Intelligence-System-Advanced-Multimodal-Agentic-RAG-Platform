from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select

from app.db import models
from app.db.base import Base, build_engine, session_scope


GRAPH_ENTITY_TYPES = {
    "Person",
    "Company",
    "Contract",
    "Clause",
    "Obligation",
    "Risk",
    "Policy",
    "Control",
    "Concept",
    "Claim",
    "Paper",
    "Table",
    "Chart",
}


@dataclass
class GraphEntityRecord:
    entity_id: str
    tenant_id: str
    workspace_id: str
    entity_type: str
    canonical_name: str
    aliases: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


@dataclass
class GraphRelationshipRecord:
    relationship_id: str
    tenant_id: str
    workspace_id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


@dataclass
class GraphFact:
    source: GraphEntityRecord
    target: GraphEntityRecord | None = None
    relationship: GraphRelationshipRecord | None = None
    evidence_anchor_id: str | None = None
    document_id: str | None = None
    page_number: int | None = None


class DisabledGraphRepository:
    enabled = False

    def upsert_entity(self, *_args, **_kwargs) -> GraphEntityRecord | None:
        return None

    def upsert_relationship(self, *_args, **_kwargs) -> GraphRelationshipRecord | None:
        return None

    def link_document_entity(self, *_args, **_kwargs) -> None:
        return None

    def link_memory_entity(self, *_args, **_kwargs) -> None:
        return None

    def search_graph(self, *_args, **_kwargs) -> list[GraphFact]:
        return []

    def index_document_graph(self, *_args, **_kwargs) -> dict[str, int]:
        return {"entities": 0, "relationships": 0}

    def status(self) -> dict[str, Any]:
        return {"enabled": False, "status": "disabled"}

    def document_counts(self, *_args, **_kwargs) -> dict[str, int] | None:
        return None

    def delete_document_graph(self, *_args, **_kwargs) -> dict[str, int]:
        return {"relationships_deleted": 0, "document_links_deleted": 0, "entities_deleted": 0, "entities_retained": 0}


class PostgresGraphRepository:
    enabled = True

    def __init__(self, database_url: str, *, create_schema: bool = True) -> None:
        self.database_url = database_url
        self.engine = build_engine(database_url)
        if create_schema:
            Base.metadata.create_all(self.engine)

    def status(self) -> dict[str, Any]:
        try:
            with self.engine.connect() as conn:
                conn.execute(select(models.GraphEntity).limit(1))
            return {"enabled": True, "status": "ok", "backend": "postgres"}
        except Exception as exc:
            return {"enabled": True, "status": "error", "backend": "postgres", "detail": str(exc)}

    def document_counts(self, *, tenant_id: str, workspace_id: str, document_id: str) -> dict[str, int]:
        with session_scope(self.database_url) as session:
            links = session.execute(
                select(models.DocumentEntity).where(models.DocumentEntity.document_id == document_id)
            ).scalars().all()
            entity_ids = {link.entity_id for link in links}
            relationships = session.execute(
                select(models.GraphRelationship).where(
                    models.GraphRelationship.tenant_id == tenant_id,
                    models.GraphRelationship.workspace_id == workspace_id,
                )
            ).scalars().all()
            related = [
                rel
                for rel in relationships
                if rel.source_entity_id in entity_ids
                or rel.target_entity_id in entity_ids
                or (rel.properties_json or {}).get("document_id") == document_id
            ]
            return {"entities": len(entity_ids), "relationships": len(related)}

    def delete_document_graph(self, *, tenant_id: str, workspace_id: str, document_id: str) -> dict[str, int]:
        from sqlalchemy import delete, func

        with session_scope(self.database_url) as session:
            links = session.execute(select(models.DocumentEntity).where(models.DocumentEntity.document_id == document_id)).scalars().all()
            entity_ids = {link.entity_id for link in links}
            relationships = session.execute(
                select(models.GraphRelationship).where(
                    models.GraphRelationship.tenant_id == tenant_id,
                    models.GraphRelationship.workspace_id == workspace_id,
                )
            ).scalars().all()
            relationship_ids = [
                rel.id
                for rel in relationships
                if rel.source_entity_id in entity_ids
                or rel.target_entity_id in entity_ids
                or (rel.properties_json or {}).get("document_id") == document_id
            ]
            if relationship_ids:
                session.execute(delete(models.GraphRelationship).where(models.GraphRelationship.id.in_(relationship_ids)))
            session.execute(delete(models.DocumentEntity).where(models.DocumentEntity.document_id == document_id))
            entities_deleted = 0
            entities_retained = 0
            for entity_id in entity_ids:
                remaining_links = session.execute(
                    select(func.count()).select_from(models.DocumentEntity).where(models.DocumentEntity.entity_id == entity_id)
                ).scalar_one()
                rel_count = session.execute(
                    select(func.count()).select_from(models.GraphRelationship).where(
                        or_(
                            models.GraphRelationship.source_entity_id == entity_id,
                            models.GraphRelationship.target_entity_id == entity_id,
                        )
                    )
                ).scalar_one()
                if remaining_links or rel_count:
                    entities_retained += 1
                    continue
                session.execute(delete(models.GraphEntity).where(models.GraphEntity.id == entity_id))
                entities_deleted += 1
            return {
                "relationships_deleted": len(relationship_ids),
                "document_links_deleted": len(links),
                "entities_deleted": entities_deleted,
                "entities_retained": entities_retained,
            }

    def upsert_entity(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        entity_type: str,
        canonical_name: str,
        aliases: list[str] | None = None,
        properties: dict[str, Any] | None = None,
        confidence: float = 0.0,
    ) -> GraphEntityRecord:
        entity_type = entity_type if entity_type in GRAPH_ENTITY_TYPES else "Concept"
        canonical_name = _normalize_name(canonical_name)
        entity_id = _stable_graph_id("entity", tenant_id, workspace_id, entity_type, canonical_name.lower())
        now = datetime.utcnow()
        with session_scope(self.database_url) as session:
            existing = session.get(models.GraphEntity, entity_id)
            merged_aliases = sorted({*(aliases or []), *((existing.aliases_json if existing else []) or [])})
            merged_properties = {**((existing.properties_json if existing else {}) or {}), **(properties or {})}
            entity = models.GraphEntity(
                id=entity_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                entity_type=entity_type,
                canonical_name=canonical_name,
                aliases_json=merged_aliases,
                properties_json=merged_properties,
                confidence=max(float(confidence), float(existing.confidence if existing else 0.0)),
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            session.merge(entity)
        return GraphEntityRecord(entity_id, tenant_id, workspace_id, entity_type, canonical_name, aliases or [], properties or {}, confidence)

    def upsert_relationship(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        source_entity_id: str,
        target_entity_id: str,
        relationship_type: str,
        properties: dict[str, Any] | None = None,
        confidence: float = 0.0,
    ) -> GraphRelationshipRecord:
        relationship_type = relationship_type.strip().upper() or "REFERENCES"
        relationship_id = _stable_graph_id("relationship", tenant_id, workspace_id, source_entity_id, relationship_type, target_entity_id)
        now = datetime.utcnow()
        with session_scope(self.database_url) as session:
            existing = session.get(models.GraphRelationship, relationship_id)
            merged_properties = {**((existing.properties_json if existing else {}) or {}), **(properties or {})}
            relationship = models.GraphRelationship(
                id=relationship_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                relationship_type=relationship_type,
                properties_json=merged_properties,
                confidence=max(float(confidence), float(existing.confidence if existing else 0.0)),
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            session.merge(relationship)
        return GraphRelationshipRecord(relationship_id, tenant_id, workspace_id, source_entity_id, target_entity_id, relationship_type, properties or {}, confidence)

    def link_document_entity(
        self,
        *,
        document_id: str,
        entity_id: str,
        evidence_anchor_id: str | None = None,
        page_number: int | None = None,
        confidence: float = 0.0,
    ) -> None:
        with session_scope(self.database_url) as session:
            session.merge(
                models.DocumentEntity(
                    document_id=document_id,
                    entity_id=entity_id,
                    evidence_anchor_id=evidence_anchor_id,
                    page_number=page_number,
                    confidence=confidence,
                )
            )

    def link_memory_entity(self, *, memory_id: str, entity_id: str, confidence: float = 0.0) -> None:
        with session_scope(self.database_url) as session:
            session.merge(models.MemoryEntity(memory_id=memory_id, entity_id=entity_id, confidence=confidence))

    def search_graph(
        self,
        query: str,
        *,
        tenant_id: str = "default-tenant",
        workspace_id: str = "default",
        entity_types: list[str] | None = None,
        limit: int = 12,
    ) -> list[GraphFact]:
        phrases = [_normalize_name(term) for term in re.findall(r"[A-Za-z][A-Za-z0-9&.-]*(?:\s+[A-Za-z][A-Za-z0-9&.-]+){0,4}", query)]
        tokens = re.findall(r"\b[A-Za-z][A-Za-z0-9&.-]{2,}\b", query)
        terms = []
        for term in [*phrases, *tokens]:
            if len(term) >= 3 and term.lower() not in {seen.lower() for seen in terms}:
                terms.append(term)
        with session_scope(self.database_url) as session:
            entity_stmt = select(models.GraphEntity).where(
                models.GraphEntity.tenant_id == tenant_id,
                models.GraphEntity.workspace_id == workspace_id,
            )
            if entity_types:
                entity_stmt = entity_stmt.where(models.GraphEntity.entity_type.in_(entity_types))
            if terms:
                entity_stmt = entity_stmt.where(or_(*(models.GraphEntity.canonical_name.ilike(f"%{term}%") for term in terms[:8])))
            entities = session.execute(entity_stmt.order_by(models.GraphEntity.confidence.desc()).limit(limit)).scalars().all()
            facts: list[GraphFact] = []
            for entity in entities:
                doc_link = session.execute(select(models.DocumentEntity).where(models.DocumentEntity.entity_id == entity.id).limit(1)).scalar_one_or_none()
                facts.append(
                    GraphFact(
                        source=self._entity_record(entity),
                        evidence_anchor_id=doc_link.evidence_anchor_id if doc_link else None,
                        document_id=doc_link.document_id if doc_link else None,
                        page_number=doc_link.page_number if doc_link else None,
                    )
                )
                rel_rows = session.execute(
                    select(models.GraphRelationship)
                    .where(
                        models.GraphRelationship.tenant_id == tenant_id,
                        models.GraphRelationship.workspace_id == workspace_id,
                        or_(models.GraphRelationship.source_entity_id == entity.id, models.GraphRelationship.target_entity_id == entity.id),
                    )
                    .order_by(models.GraphRelationship.confidence.desc())
                    .limit(3)
                ).scalars().all()
                for rel in rel_rows:
                    other_id = rel.target_entity_id if rel.source_entity_id == entity.id else rel.source_entity_id
                    other = session.get(models.GraphEntity, other_id)
                    if other is None:
                        continue
                    props = rel.properties_json or {}
                    facts.append(
                        GraphFact(
                            source=self._entity_record(entity),
                            target=self._entity_record(other),
                            relationship=self._relationship_record(rel),
                            evidence_anchor_id=props.get("evidence_anchor_id"),
                            document_id=props.get("document_id"),
                            page_number=props.get("page_number"),
                        )
                    )
            return facts[:limit]

    def index_document_graph(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        document_id: str,
        filename: str,
        pages: list[dict],
    ) -> dict[str, int]:
        extractor = GraphExtractor()
        candidates = extractor.extract_document(filename=filename, pages=pages)
        entities_by_key: dict[tuple[str, str], GraphEntityRecord] = {}
        relationship_count = 0
        for candidate in candidates["entities"]:
            entity = self.upsert_entity(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                entity_type=candidate["entity_type"],
                canonical_name=candidate["canonical_name"],
                aliases=candidate.get("aliases", []),
                properties={k: v for k, v in candidate.items() if k not in {"entity_type", "canonical_name", "aliases"}},
                confidence=candidate.get("confidence", 0.6),
            )
            entities_by_key[(candidate["entity_type"], _normalize_name(candidate["canonical_name"]).lower())] = entity
            self.link_document_entity(
                document_id=document_id,
                entity_id=entity.entity_id,
                evidence_anchor_id=candidate.get("evidence_anchor_id"),
                page_number=candidate.get("page_number"),
                confidence=candidate.get("confidence", 0.6),
            )
        for candidate in candidates["relationships"]:
            source_key = (candidate["source_type"], _normalize_name(candidate["source_name"]).lower())
            target_key = (candidate["target_type"], _normalize_name(candidate["target_name"]).lower())
            source = entities_by_key.get(source_key)
            if source is None:
                source = self.upsert_entity(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    entity_type=candidate["source_type"],
                    canonical_name=candidate["source_name"],
                    properties={"document_id": document_id, "page_number": candidate.get("page_number")},
                    confidence=candidate.get("confidence", 0.6),
                )
                entities_by_key[source_key] = source
            target = entities_by_key.get(target_key)
            if target is None:
                target = self.upsert_entity(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    entity_type=candidate["target_type"],
                    canonical_name=candidate["target_name"],
                    properties={"document_id": document_id, "page_number": candidate.get("page_number")},
                    confidence=candidate.get("confidence", 0.6),
                )
                entities_by_key[target_key] = target
            self.upsert_relationship(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                source_entity_id=source.entity_id,
                target_entity_id=target.entity_id,
                relationship_type=candidate["relationship_type"],
                properties={
                    "document_id": document_id,
                    "page_number": candidate.get("page_number"),
                    "evidence_anchor_id": candidate.get("evidence_anchor_id"),
                    "text": candidate.get("text", "")[:500],
                },
                confidence=candidate.get("confidence", 0.6),
            )
            relationship_count += 1
        return {"entities": len(entities_by_key), "relationships": relationship_count}

    @staticmethod
    def _entity_record(row: models.GraphEntity) -> GraphEntityRecord:
        return GraphEntityRecord(row.id, row.tenant_id, row.workspace_id, row.entity_type, row.canonical_name, row.aliases_json or [], row.properties_json or {}, row.confidence)

    @staticmethod
    def _relationship_record(row: models.GraphRelationship) -> GraphRelationshipRecord:
        return GraphRelationshipRecord(row.id, row.tenant_id, row.workspace_id, row.source_entity_id, row.target_entity_id, row.relationship_type, row.properties_json or {}, row.confidence)


class GraphExtractor:
    COMPANY_SUFFIX = r"(?:Inc\.?|LLC|Ltd\.?|Limited|Corporation|Corp\.?|Company|Co\.?|Pvt\.?|Private Limited)"
    RELATIONSHIP_PATTERNS = (
        ("CREATES_OBLIGATION", r"(?P<source>[A-Z][A-Za-z0-9&., ]{2,80})\s+(?:shall|must|is required to|agrees to)\s+(?P<target>[^.]{8,180})"),
        ("HAS_RISK", r"(?P<source>[A-Z][A-Za-z0-9&., ]{2,80})\s+(?:faces|has|carries|creates)\s+(?P<target>[^.]{4,120}risk[^.]*)"),
        ("SUPPORTS_CLAIM", r"(?P<source>[A-Z][A-Za-z0-9&., ]{2,80})\s+(?:shows|indicates|supports|demonstrates)\s+(?P<target>[^.]{8,180})"),
    )

    def __init__(self, hf_registry=None) -> None:
        self.hf_registry = hf_registry

    def extract_document(self, *, filename: str, pages: list[dict]) -> dict[str, list[dict[str, Any]]]:
        entities: list[dict[str, Any]] = [
            {
                "entity_type": "Contract" if "contract" in filename.lower() else "Paper" if "paper" in filename.lower() else "Concept",
                "canonical_name": filename,
                "confidence": 0.9,
                "source": "filename",
            }
        ]
        relationships: list[dict[str, Any]] = []
        for page in pages:
            page_number = int(page.get("page_number") or 1)
            metadata = page.get("metadata", {}) or {}
            text = page.get("text", "") or ""
            entities.extend(self._artifact_entities(metadata, page_number))
            entities.extend(self._text_entities(text, page_number))
            entities.extend(self._hf_entities(text, page_number))
            relationships.extend(self._artifact_relationships(filename, metadata, page_number))
            relationships.extend(self._text_relationships(text, page_number))
        return {"entities": _dedupe_entities(entities), "relationships": relationships}

    def _hf_entities(self, text: str, page_number: int) -> list[dict[str, Any]]:
        if self.hf_registry is None or not text:
            return []
        extractor = getattr(self.hf_registry, "extract_entities", None)
        if not callable(extractor):
            return []
        try:
            payload = extractor(text)
        except Exception:
            return []
        return [
            {
                "entity_type": "Concept",
                "canonical_name": entity,
                "confidence": 0.62,
                "page_number": page_number,
                "source": "huggingface_entity_extraction",
            }
            for entity in payload.get("entities", [])[:30]
        ]

    def _artifact_entities(self, metadata: dict[str, Any], page_number: int) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        artifact_specs = [
            ("clauses", "Clause"),
            ("risks", "Risk"),
            ("definitions", "Concept"),
            ("tables", "Table"),
            ("charts", "Chart"),
        ]
        for key, entity_type in artifact_specs:
            for item in metadata.get(key, []) or []:
                name = item.get("title") or item.get("tag") or item.get("caption")
                if not name:
                    continue
                entities.append(
                    {
                        "entity_type": entity_type,
                        "canonical_name": str(name),
                        "confidence": 0.85,
                        "page_number": page_number,
                        "evidence_anchor_id": item.get("artifact_id") or item.get("anchor_id"),
                        "text": item.get("text") or item.get("caption") or "",
                    }
                )
        return entities

    def _artifact_relationships(self, filename: str, metadata: dict[str, Any], page_number: int) -> list[dict[str, Any]]:
        relationships: list[dict[str, Any]] = []
        for clause in metadata.get("clauses", []) or []:
            name = clause.get("title")
            if name:
                relationships.append(self._relationship(filename, "Contract", name, "Clause", "CONTAINS_CLAUSE", page_number, clause))
            text = clause.get("text", "")
            if re.search(r"\b(shall|must|required to|agrees to)\b", text, re.IGNORECASE):
                obligation_name = text[:120]
                relationships.append(self._relationship(name or filename, "Clause", obligation_name, "Obligation", "CREATES_OBLIGATION", page_number, clause))
        for risk in metadata.get("risks", []) or []:
            risk_name = risk.get("title") or risk.get("tag")
            if risk_name:
                relationships.append(self._relationship(filename, "Contract", risk_name, "Risk", "HAS_RISK", page_number, risk))
        return relationships

    def _text_entities(self, text: str, page_number: int) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        for match in re.findall(rf"\b([A-Z][A-Za-z0-9&., ]{{2,80}}\s+{self.COMPANY_SUFFIX})\b", text):
            entities.append({"entity_type": "Company", "canonical_name": match.strip(" .,;"), "confidence": 0.72, "page_number": page_number, "text": match})
        for match in re.findall(r"\b([A-Z][a-z]{2,}\s+[A-Z][a-z]{2,})\b", text):
            if any(skip in match.lower() for skip in {"limited", "company", "contract", "agreement"}):
                continue
            entities.append({"entity_type": "Person", "canonical_name": match.strip(), "confidence": 0.55, "page_number": page_number, "text": match})
        for match in re.findall(r"\b(?:means|defined as)\s+([A-Z][A-Za-z0-9& -]{3,80})", text):
            entities.append({"entity_type": "Concept", "canonical_name": match.strip(" .,;"), "confidence": 0.58, "page_number": page_number, "text": match})
        return entities[:40]

    def _text_relationships(self, text: str, page_number: int) -> list[dict[str, Any]]:
        relationships: list[dict[str, Any]] = []
        for relationship_type, pattern in self.RELATIONSHIP_PATTERNS:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                source = _normalize_name(match.group("source").strip(" .,;"))
                target = _normalize_name(match.group("target").strip(" .,;"))
                target_type = "Risk" if relationship_type == "HAS_RISK" else "Obligation" if relationship_type == "CREATES_OBLIGATION" else "Claim"
                relationships.append(
                    {
                        "source_name": source,
                        "source_type": "Company",
                        "target_name": target[:160],
                        "target_type": target_type,
                        "relationship_type": relationship_type,
                        "page_number": page_number,
                        "text": match.group(0),
                        "confidence": 0.52,
                    }
                )
        return relationships[:20]

    @staticmethod
    def _relationship(source_name: str, source_type: str, target_name: str, target_type: str, relationship_type: str, page_number: int, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_name": source_name,
            "source_type": source_type,
            "target_name": target_name,
            "target_type": target_type,
            "relationship_type": relationship_type,
            "page_number": page_number,
            "evidence_anchor_id": payload.get("artifact_id") or payload.get("anchor_id"),
            "text": payload.get("text") or payload.get("caption") or payload.get("title") or "",
            "confidence": 0.78,
        }


def _dedupe_entities(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for entity in entities:
        name = _normalize_name(str(entity.get("canonical_name", "")))
        if len(name) < 3:
            continue
        key = (str(entity.get("entity_type", "Concept")), name.lower())
        if key in seen:
            continue
        seen.add(key)
        entity["canonical_name"] = name
        deduped.append(entity)
    return deduped


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" .,;:\n\t")


def _stable_graph_id(namespace: str, *parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "aiwana:graph:" + namespace + ":" + ":".join(parts)))
