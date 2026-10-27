from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as rest
except Exception:  # pragma: no cover - optional dependency in static environments
    QdrantClient = None
    rest = None


@dataclass(frozen=True)
class QdrantPayloadFilter:
    tenant_id: str | None = None
    workspace_id: str | None = None
    document_id: str | list[str] | None = None
    page_number: int | list[int] | None = None
    content_type: str | list[str] | None = None
    objective_profile: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "document_id": self.document_id,
            "page_number": self.page_number,
            "content_type": self.content_type,
            "objective_profile": self.objective_profile,
            **self.extra,
        }
        return {key: value for key, value in payload.items() if value is not None and value != []}


@dataclass(frozen=True)
class SparseVectorPayload:
    indices: list[int]
    values: list[float]


class QdrantVectorStore:
    def __init__(self, url: str, collection_name: str, fallback_url: str | None = None, use_named_vectors: bool = False, use_sparse_vectors: bool = False) -> None:
        self.url = url
        self.fallback_url = fallback_url
        self.collection_name = collection_name
        self.use_named_vectors = use_named_vectors
        self.use_sparse_vectors = use_sparse_vectors
        self.text_vector_name = "text_dense"
        self.sparse_vector_name = "text_sparse"
        self._fallback: dict[str, dict[str, Any]] = {}
        self.active_url = url
        self.client = self._build_client(url) if QdrantClient else None
        if self.client is None and fallback_url:
            self.active_url = fallback_url
            self.client = self._build_client(fallback_url)
        elif self.client is not None and not self.is_available() and fallback_url:
            self.client = self._build_client(fallback_url)
            self.active_url = fallback_url

    def _build_client(self, url: str):
        if QdrantClient is None:
            return None
        if url == ":memory:":
            return QdrantClient(location=":memory:")
        if url.startswith("file://"):
            local_path = Path(url.removeprefix("file://"))
            local_path.mkdir(parents=True, exist_ok=True)
            try:
                return QdrantClient(path=str(local_path))
            except Exception:
                return None
        try:
            return QdrantClient(url=url)
        except Exception:
            return None

    def ensure_collection(self, vector_size: int) -> None:
        if self.client is None or rest is None:
            return
        try:
            collections = {item.name for item in self.client.get_collections().collections}
        except Exception:
            return
        if self.collection_name not in collections:
            vectors_config = (
                {
                    self.text_vector_name: rest.VectorParams(size=vector_size, distance=rest.Distance.COSINE),
                    "visual_dense": rest.VectorParams(size=vector_size, distance=rest.Distance.COSINE),
                    "table_dense": rest.VectorParams(size=vector_size, distance=rest.Distance.COSINE),
                }
                if self.use_named_vectors
                else rest.VectorParams(size=vector_size, distance=rest.Distance.COSINE)
            )
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=vectors_config,
                sparse_vectors_config=self._sparse_vectors_config() if self.use_sparse_vectors else None,
            )
        else:
            self._ensure_named_vectors(vector_size)
            if self.use_sparse_vectors:
                self._ensure_sparse_vectors()
        self._ensure_payload_indexes()

    def collection_report(self) -> dict[str, Any]:
        report: dict[str, Any] = {
            "collection": self.collection_name,
            "location": self.get_active_location(),
            "available": self.is_available(),
            "points_count": self.count(),
            "named_vectors": [],
            "sparse_vectors": [],
            "payload_indexes": {},
        }
        if self.client is None or rest is None:
            return report
        try:
            info = self.client.get_collection(self.collection_name)
        except Exception as exc:
            report["error"] = str(exc)
            return report
        params = info.config.params
        vectors = getattr(params, "vectors", None) or {}
        if isinstance(vectors, dict):
            report["named_vectors"] = sorted(vectors.keys())
            report["vector_sizes"] = {name: getattr(config, "size", None) for name, config in vectors.items()}
        else:
            report["named_vectors"] = ["default"]
            report["vector_sizes"] = {"default": getattr(vectors, "size", None)}
        sparse_vectors = getattr(params, "sparse_vectors", None) or {}
        report["sparse_vectors"] = sorted(sparse_vectors.keys()) if isinstance(sparse_vectors, dict) else []
        payload_schema = getattr(info, "payload_schema", None) or {}
        report["payload_indexes"] = {
            name: getattr(schema, "data_type", str(schema)).value if hasattr(getattr(schema, "data_type", None), "value") else str(getattr(schema, "data_type", schema))
            for name, schema in payload_schema.items()
        }
        report["status"] = getattr(getattr(info, "status", None), "value", str(getattr(info, "status", "")))
        return report

    def verify_collection(self, vector_size: int = 1024) -> dict[str, Any]:
        try:
            self.ensure_collection(vector_size)
        except Exception as exc:
            return {
                "collection": self.collection_name,
                "location": self.get_active_location(),
                "available": False,
                "error": str(exc),
                "missing_named_vectors": [],
                "missing_sparse_vectors": [],
                "missing_payload_indexes": [],
                "ok": False,
            }
        report = self.collection_report()
        required_vectors = {self.text_vector_name, "visual_dense", "table_dense"} if self.use_named_vectors else {"default"}
        required_payload_indexes = {"tenant_id", "workspace_id", "document_id", "page_number", "content_type", "objective_profile"}
        report["missing_named_vectors"] = sorted(required_vectors - set(report.get("named_vectors", [])))
        report["missing_sparse_vectors"] = [self.sparse_vector_name] if self.use_sparse_vectors and self.sparse_vector_name not in set(report.get("sparse_vectors", [])) else []
        report["missing_payload_indexes"] = sorted(required_payload_indexes - set(report.get("payload_indexes", {}).keys()))
        report["ok"] = not (report["missing_named_vectors"] or report["missing_sparse_vectors"] or report["missing_payload_indexes"])
        return report

    def verify_server_side_filters(self, vector_size: int = 1024) -> dict[str, Any]:
        probe_filters = QdrantPayloadFilter(
            tenant_id="__aiwana_filter_probe_tenant__",
            workspace_id="__aiwana_filter_probe_workspace__",
            document_id="__aiwana_filter_probe_document__",
            objective_profile="__aiwana_filter_probe_objective__",
        ).as_dict()
        server_side = not (self.active_url.startswith("file://") or self.active_url == ":memory:")
        if self.client is None:
            results = self.query([0.001] * vector_size, limit=1, filters=probe_filters)
            return {
                "ok": not results,
                "server_side": False,
                "fallback_filter_checked": True,
                "probe_filters": probe_filters,
                "result_count": len(results),
            }
        if server_side and not self.is_available():
            return {
                "ok": False,
                "server_side": True,
                "probe_filters": probe_filters,
                "error": "Qdrant server is unavailable; payload filter probe could not run.",
            }
        try:
            results = self.query([0.001] * vector_size, limit=1, filters=probe_filters)
        except Exception as exc:
            return {"ok": False, "server_side": server_side, "probe_filters": probe_filters, "error": str(exc)}
        return {
            "ok": not results,
            "server_side": server_side,
            "probe_filters": probe_filters,
            "result_count": len(results),
        }

    def _sparse_vectors_config(self) -> dict[str, Any]:
        return {self.sparse_vector_name: rest.SparseVectorParams()}

    def _ensure_sparse_vectors(self) -> None:
        if self.client is None or rest is None:
            return
        try:
            info = self.client.get_collection(self.collection_name)
            configured = getattr(info.config.params, "sparse_vectors", None) or {}
            if self.sparse_vector_name not in configured:
                self.client.update_collection(self.collection_name, sparse_vectors_config=self._sparse_vectors_config())
        except Exception:
            return

    def _ensure_named_vectors(self, vector_size: int) -> None:
        if not self.use_named_vectors or self.client is None or rest is None:
            return
        try:
            info = self.client.get_collection(self.collection_name)
            configured = getattr(info.config.params, "vectors", None) or {}
            if not isinstance(configured, dict):
                return
            missing = {
                name: rest.VectorParams(size=vector_size, distance=rest.Distance.COSINE)
                for name in (self.text_vector_name, "visual_dense", "table_dense")
                if name not in configured
            }
            if missing:
                self.client.update_collection(self.collection_name, vectors_config=missing)
        except Exception:
            return

    def _ensure_payload_indexes(self) -> None:
        if self.client is None or rest is None:
            return
        for field_name in ("tenant_id", "workspace_id", "document_id", "page_number", "content_type", "objective_profile"):
            try:
                schema = rest.PayloadSchemaType.INTEGER if field_name == "page_number" else rest.PayloadSchemaType.KEYWORD
                self.client.create_payload_index(self.collection_name, field_name=field_name, field_schema=schema)
            except Exception:
                continue

    def upsert(self, ids: list[str], vectors: list[list[float]], payloads: list[dict[str, Any]], sparse_vectors: list[dict[int, float]] | None = None) -> None:
        if not ids:
            return
        if self.client is None or rest is None:
            for point_id, vector, payload in zip(ids, vectors, payloads):
                self._fallback[point_id] = {"vector": vector, "payload": payload}
            return
        self.ensure_collection(len(vectors[0]))
        sparse_vectors = sparse_vectors or []
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                rest.PointStruct(id=point_id, vector=self._point_vector(vector, sparse_vectors[index] if index < len(sparse_vectors) else None, payload), payload=payload)
                for index, (point_id, vector, payload) in enumerate(zip(ids, vectors, payloads))
            ],
        )

    def _point_vector(self, dense_vector: list[float], sparse_vector: dict[int, float] | None = None, payload: dict[str, Any] | None = None):
        if not self.use_named_vectors and not (self.use_sparse_vectors and sparse_vector):
            return dense_vector
        vector: dict[str, Any] = {self.text_vector_name: dense_vector}
        content_type = (payload or {}).get("content_type")
        if self.use_named_vectors and content_type in {"table", "chart"}:
            vector["table_dense"] = dense_vector
        if self.use_named_vectors and content_type in {"visual_text", "image", "figure", "chart"}:
            vector["visual_dense"] = dense_vector
        if self.use_sparse_vectors and sparse_vector:
            indices = list(sparse_vector.keys())
            values = list(sparse_vector.values())
            vector[self.sparse_vector_name] = (
                rest.SparseVector(indices=indices, values=values)
                if rest is not None
                else SparseVectorPayload(indices=indices, values=values)
            )
        return vector

    def query(
        self,
        vector: list[float],
        limit: int = 5,
        vector_name: str | None = None,
        filters: dict[str, Any] | QdrantPayloadFilter | None = None,
    ) -> list[dict[str, Any]]:
        normalized_filters = self._normalize_filters(filters)
        if self.client is None:
            scored = []
            for point_id, item in self._fallback.items():
                if not self._payload_matches(item.get("payload", {}), normalized_filters):
                    continue
                score = self._cosine(vector, item["vector"])
                scored.append({"id": point_id, "score": score, "payload": item["payload"]})
            return sorted(scored, key=lambda item: item["score"], reverse=True)[:limit]
        try:
            points = self.client.query_points(
                collection_name=self.collection_name,
                query=vector,
                using=vector_name or (self.text_vector_name if self.use_named_vectors else None),
                query_filter=self._build_filter(normalized_filters),
                limit=limit,
                with_payload=True,
            ).points
        except Exception:
            return []
        return [{"id": point.id, "score": point.score, "payload": point.payload} for point in points]

    def query_sparse(self, sparse_vector: dict[int, float], limit: int = 5, filters: dict[str, Any] | QdrantPayloadFilter | None = None) -> list[dict[str, Any]]:
        if not sparse_vector or self.client is None or rest is None or not self.use_sparse_vectors:
            return []
        normalized_filters = self._normalize_filters(filters)
        try:
            points = self.client.query_points(
                collection_name=self.collection_name,
                query=rest.SparseVector(indices=list(sparse_vector.keys()), values=list(sparse_vector.values())),
                using=self.sparse_vector_name,
                query_filter=self._build_filter(normalized_filters),
                limit=limit,
                with_payload=True,
            ).points
        except Exception:
            return []
        return [{"id": point.id, "score": point.score, "payload": point.payload} for point in points]

    def delete(self, ids: list[str]) -> None:
        if not ids:
            return
        if self.client is None or rest is None:
            for point_id in ids:
                self._fallback.pop(point_id, None)
            return
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=rest.PointIdsList(points=ids),
        )

    def count(self, filters: dict[str, Any] | QdrantPayloadFilter | None = None) -> int:
        normalized_filters = self._normalize_filters(filters)
        if self.client is None:
            if not normalized_filters:
                return len(self._fallback)
            return sum(1 for item in self._fallback.values() if self._payload_matches(item.get("payload", {}), normalized_filters))
        try:
            return self.client.count(self.collection_name, exact=True, count_filter=self._build_filter(normalized_filters)).count
        except Exception:
            return 0

    def create_snapshot(self) -> dict[str, Any]:
        if self.client is None:
            return {"status": "blocked", "error": "Qdrant client is unavailable; cannot create a server snapshot.", "collection": self.collection_name}
        try:
            snapshot = self.client.create_snapshot(collection_name=self.collection_name)
            return {"status": "ok", "collection": self.collection_name, "snapshot": self._snapshot_payload(snapshot)}
        except Exception as exc:
            return {"status": "blocked", "collection": self.collection_name, "error": str(exc)}

    def list_snapshots(self) -> dict[str, Any]:
        if self.client is None:
            return {"status": "blocked", "error": "Qdrant client is unavailable; cannot list server snapshots.", "collection": self.collection_name, "snapshots": []}
        try:
            snapshots = self.client.list_snapshots(collection_name=self.collection_name)
            return {"status": "ok", "collection": self.collection_name, "snapshots": [self._snapshot_payload(snapshot) for snapshot in snapshots]}
        except Exception as exc:
            return {"status": "blocked", "collection": self.collection_name, "error": str(exc), "snapshots": []}

    def restore_snapshot(self, snapshot_location: str, *, wait: bool = True) -> dict[str, Any]:
        if self.client is None:
            return {"status": "blocked", "error": "Qdrant client is unavailable; cannot restore a server snapshot.", "collection": self.collection_name}
        recover = getattr(self.client, "recover_snapshot", None)
        if not callable(recover):
            return {"status": "blocked", "error": "Installed qdrant-client does not expose recover_snapshot.", "collection": self.collection_name}
        try:
            result = recover(collection_name=self.collection_name, location=snapshot_location, wait=wait)
            return {"status": "ok", "collection": self.collection_name, "snapshot_location": snapshot_location, "result": str(result)}
        except Exception as exc:
            return {"status": "blocked", "collection": self.collection_name, "snapshot_location": snapshot_location, "error": str(exc)}

    def is_available(self) -> bool:
        if self.client is None:
            return False
        try:
            if self.active_url.startswith("file://") or self.active_url == ":memory:":
                return True
            self.client.get_collections()
            return True
        except Exception:
            return False

    def get_active_location(self) -> str:
        return self.active_url

    def _build_filter(self, filters: dict[str, Any] | None):
        if not filters or rest is None:
            return None
        must = []
        for key in ("tenant_id", "workspace_id", "document_id", "page_number", "content_type", "objective_profile"):
            value = filters.get(key)
            if value is None or value == []:
                continue
            if isinstance(value, (list, tuple, set)):
                must.append(rest.FieldCondition(key=key, match=rest.MatchAny(any=list(value))))
            else:
                must.append(rest.FieldCondition(key=key, match=rest.MatchValue(value=value)))
        return rest.Filter(must=must) if must else None

    @staticmethod
    def _normalize_filters(filters: dict[str, Any] | QdrantPayloadFilter | None) -> dict[str, Any] | None:
        if filters is None:
            return None
        if isinstance(filters, QdrantPayloadFilter):
            return filters.as_dict()
        return filters

    @staticmethod
    def _payload_matches(payload: dict[str, Any], filters: dict[str, Any] | None) -> bool:
        if not filters:
            return True
        for key, value in filters.items():
            if value is None or value == []:
                continue
            actual = payload.get(key)
            if isinstance(value, (list, tuple, set)):
                if actual not in value:
                    return False
            elif actual != value:
                return False
        return True

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        numerator = sum(a * b for a, b in zip(left, right))
        left_norm = sum(a * a for a in left) ** 0.5
        right_norm = sum(b * b for b in right) ** 0.5
        if not left_norm or not right_norm:
            return 0.0
        return numerator / (left_norm * right_norm)

    @staticmethod
    def _snapshot_payload(snapshot: Any) -> dict[str, Any]:
        if isinstance(snapshot, dict):
            return snapshot
        payload: dict[str, Any] = {}
        for name in ("name", "creation_time", "size", "checksum"):
            value = getattr(snapshot, name, None)
            if value is not None:
                payload[name] = value
        return payload or {"value": str(snapshot)}
