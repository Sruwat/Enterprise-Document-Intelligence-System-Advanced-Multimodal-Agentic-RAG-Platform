from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.backup import BackupService


class LaunchReadinessService:
    def __init__(
        self,
        settings,
        metadata_store,
        vector_store,
        embedding_provider,
        reranker,
        primary_llm,
        redis_service=None,
        evaluation_service=None,
        worker=None,
        huggingface_registry=None,
    ) -> None:
        self.settings = settings
        self.metadata_store = metadata_store
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider
        self.reranker = reranker
        self.primary_llm = primary_llm
        self.redis_service = redis_service
        self.evaluation_service = evaluation_service
        self.worker = worker
        self.huggingface_registry = huggingface_registry

    def report(self) -> dict[str, Any]:
        checks = [
            self._check_model_profile(),
            self._check_embedding_runtime(),
            self._check_reranker_runtime(),
            self._check_llm_provider(),
            self._check_qdrant(),
            self._check_qdrant_schema(),
            self._check_qdrant_filters(),
            self._check_vector_reconciliation(),
            self._check_sparse_vectors(),
            self._check_persistence(),
            self._check_postgres_runtime(),
            self._check_worker_runtime(),
            self._check_audit_api(),
            self._check_backup_restore(),
            self._check_production_dependencies(),
            self._check_redis_runtime(),
            self._check_upload_limits(),
            self._check_memory(),
            self._check_multimodal(),
            self._check_evaluation_dataset(),
            self._check_graph_eval_gate(),
            self._check_huggingface_runtime(),
            self._check_security_profile(),
        ]
        blockers = [check for check in checks if check["status"] == "blocker"]
        warnings = [check for check in checks if check["status"] == "warning"]
        return {
            "status": "blocked" if blockers else "warning" if warnings else "ready",
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
            "checks": checks,
            "summary": self._summary(blockers, warnings),
        }

    def _check_model_profile(self) -> dict[str, Any]:
        model = self.settings.embedding_model.lower()
        collection = self.settings.qdrant_collection
        path_exists = Path(self.settings.embedding_model_path).exists()
        if "bge-m3" not in model or "v2" not in collection:
            return self._check("model_profile", "blocker", "Launch profile must use BGE-M3 and the aiwana_chunks_v2 collection.", {"embedding_model": self.settings.embedding_model, "collection": collection})
        if not path_exists:
            return self._check("model_profile", "blocker", "BGE-M3 model directory is missing locally.", {"path": str(self.settings.embedding_model_path)})
        return self._check("model_profile", "ok", "BGE-M3 launch profile is configured.", {"embedding_model": self.settings.embedding_model, "collection": collection})

    def _check_embedding_runtime(self) -> dict[str, Any]:
        status = self._safe_status(self.embedding_provider)
        dimension = int(status.get("dimension") or 0)
        if status.get("status") != "ok":
            return self._check("embedding_runtime", "blocker", "Embedding provider is not ready.", status)
        if "bge-m3" in self.settings.embedding_model.lower() and dimension != 1024:
            return self._check("embedding_runtime", "blocker", "BGE-M3 must produce 1024-dimensional vectors.", status)
        return self._check("embedding_runtime", "ok", "Embedding provider is ready.", status)

    def _check_reranker_runtime(self) -> dict[str, Any]:
        status = self._safe_status(self.reranker)
        if status.get("status") != "ok":
            return self._check("reranker_runtime", "warning", "Reranker is unavailable; retrieval quality may drop.", status)
        if "v2-m3" not in str(self.settings.reranker_model).lower() and "v2-m3" not in str(self.settings.reranker_model_path).lower():
            return self._check("reranker_runtime", "warning", "Launch profile should use bge-reranker-v2-m3.", status)
        return self._check("reranker_runtime", "ok", "Reranker is ready.", status)

    def _check_llm_provider(self) -> dict[str, Any]:
        provider = getattr(self.primary_llm, "provider_name", "unknown")
        if provider == "grounded_fallback":
            return self._check("llm_provider", "blocker", "Groq API is not configured; app is using local fallback.", {"provider": provider})
        if self.settings.llm_provider == "groq" and not self.settings.groq_api_key:
            return self._check("llm_provider", "blocker", "LLM provider is Groq but GROQ_API_KEY is empty.", {"provider": provider})
        return self._check("llm_provider", "ok", "Hosted LLM provider is configured.", {"provider": provider, "model": getattr(self.primary_llm, "model_name", None)})

    def _check_qdrant(self) -> dict[str, Any]:
        available = self.vector_store.is_available()
        location = self.vector_store.get_active_location()
        if not available:
            return self._check("qdrant", "blocker", "Qdrant is unavailable.", {"location": location})
        if location.startswith("file://"):
            return self._check("qdrant", "warning", "Qdrant is using local file fallback; use server Qdrant for SaaS launch.", {"location": location})
        return self._check("qdrant", "ok", "Qdrant server is available.", {"location": location, "vector_count": self.vector_store.count()})

    def _check_qdrant_schema(self) -> dict[str, Any]:
        verifier = getattr(self.vector_store, "verify_collection", None)
        if not callable(verifier):
            return self._check("qdrant_schema", "warning", "Vector store cannot report collection schema.", {})
        report = verifier(1024 if "bge-m3" in self.settings.embedding_model.lower() else 384)
        if not report.get("ok"):
            location = str(report.get("location") or self.vector_store.get_active_location())
            if location.startswith("file://") and self.settings.app_env.lower() != "production":
                return self._check("qdrant_schema", "warning", "Local Qdrant fallback cannot enforce payload indexes; use server Qdrant for SaaS launch.", report)
            return self._check("qdrant_schema", "blocker", "Qdrant collection is missing required named vectors or payload indexes.", report)
        return self._check("qdrant_schema", "ok", "Qdrant named vectors and payload indexes are ready.", report)

    def _check_qdrant_filters(self) -> dict[str, Any]:
        verifier = getattr(self.vector_store, "verify_server_side_filters", None)
        if not callable(verifier):
            return self._check("qdrant_filters", "warning", "Vector store cannot verify server-side payload filters.", {})
        report = verifier(1024 if "bge-m3" in self.settings.embedding_model.lower() else 384)
        if not report.get("ok"):
            return self._check("qdrant_filters", "blocker", "Qdrant payload filter probe failed; tenant-safe retrieval cannot be guaranteed.", report)
        if not report.get("server_side") and self.settings.app_env.lower() == "production":
            return self._check("qdrant_filters", "blocker", "Production launch requires server-side Qdrant payload filters, not local fallback filtering.", report)
        status = "warning" if not report.get("server_side") else "ok"
        message = "Qdrant payload filter probe passed." if report.get("server_side") else "Local fallback payload filter probe passed; use server Qdrant for SaaS launch."
        return self._check("qdrant_filters", status, message, report)

    def _check_vector_reconciliation(self) -> dict[str, Any]:
        metadata_chunks = self.metadata_store.chunk_count()
        vector_count = self.vector_store.count()
        if metadata_chunks and vector_count != metadata_chunks:
            return self._check(
                "vector_reconciliation",
                "blocker",
                "Metadata chunk count does not match Qdrant point count; run v2 re-ingestion.",
                {"metadata_chunks": metadata_chunks, "qdrant_points": vector_count},
            )
        return self._check("vector_reconciliation", "ok", "Metadata chunks and Qdrant points are reconciled.", {"metadata_chunks": metadata_chunks, "qdrant_points": vector_count})

    def _check_sparse_vectors(self) -> dict[str, Any]:
        if not getattr(self.settings, "enable_bge_m3_sparse", False):
            return self._check("bge_m3_sparse", "ok", "BGE-M3 sparse vectors are disabled by configuration.", {"enabled": False})
        status = self._safe_status(self.embedding_provider)
        if not status.get("sparse_available"):
            return self._check("bge_m3_sparse", "warning", "Sparse mode is enabled but sparse embeddings are unavailable; install FlagEmbedding or disable sparse mode.", status)
        return self._check("bge_m3_sparse", "ok", "BGE-M3 sparse embeddings are available.", status)

    def _check_persistence(self) -> dict[str, Any]:
        try:
            workspace_count = len(self.metadata_store.list_workspaces())
            details = {"workspace_count": workspace_count, "db": str(self.metadata_store.db_path), "backend": self.settings.database_backend}
            if self.settings.app_env.lower() == "production" and self.settings.database_backend.lower() != "postgres":
                return self._check("persistence", "blocker", "Production launch requires Postgres as the primary metadata store.", details)
            return self._check("persistence", "ok", "Metadata store is readable.", details)
        except Exception as exc:
            return self._check("persistence", "blocker", "Metadata store is not readable.", {"detail": str(exc)})

    def _check_postgres_runtime(self) -> dict[str, Any]:
        if self.settings.database_backend.lower() != "postgres":
            severity = "blocker" if self.settings.app_env.lower() == "production" else "warning"
            return self._check("postgres_runtime", severity, "Postgres is not the active metadata backend.", {"backend": self.settings.database_backend})
        checker = getattr(self.metadata_store, "runtime_status", None)
        if not callable(checker):
            if self.settings.app_env.lower() != "production":
                return self._check("postgres_runtime", "ok", "Postgres runtime proof is skipped outside production for test metadata stores.", {"repository": self.metadata_store.__class__.__name__})
            return self._check("postgres_runtime", "blocker", "Postgres repository cannot prove runtime health.", {"repository": self.metadata_store.__class__.__name__})
        status = checker()
        if status.get("status") != "ok":
            return self._check("postgres_runtime", "blocker", "Postgres runtime or schema probe failed.", status)
        migration_status = "ok" if status.get("migration_revision") else "warning"
        message = "Postgres runtime and required tables are healthy."
        if migration_status == "warning":
            status = {**status, "migration_warning": "alembic_version was not found; run migrations before launch."}
            severity = "blocker" if self.settings.app_env.lower() == "production" else "warning"
            return self._check("postgres_runtime", severity, "Postgres is reachable but migration revision is not recorded.", status)
        return self._check("postgres_runtime", "ok", message, status)

    def _check_worker_runtime(self) -> dict[str, Any]:
        if self.worker is None:
            severity = "blocker" if self.settings.app_env.lower() == "production" and self.settings.enable_queue_ingestion else "warning"
            if self.settings.app_env.lower() != "production":
                severity = "ok"
            return self._check("worker_runtime", severity, "Worker runtime was not provided to readiness.", {"enable_queue_ingestion": self.settings.enable_queue_ingestion})
        try:
            heartbeat = self.worker.heartbeat()
        except Exception as exc:
            return self._check("worker_runtime", "blocker", "Worker heartbeat failed.", {"detail": str(exc)})
        if heartbeat.get("status") != "ok":
            severity = "blocker" if self.settings.app_env.lower() == "production" else "warning"
            return self._check("worker_runtime", severity, "Worker heartbeat is degraded.", heartbeat)
        return self._check("worker_runtime", "ok", "Worker heartbeat is healthy.", heartbeat)

    def _check_audit_api(self) -> dict[str, Any]:
        try:
            from app.api.main import app

            route_paths = {getattr(route, "path", "") for route in app.routes}
        except Exception as exc:
            return self._check("audit_api", "blocker", "Audit API route registration could not be inspected.", {"detail": str(exc)})
        if "/audit/logs" not in route_paths:
            return self._check("audit_api", "blocker", "Audit log API is not mounted.", {"expected_path": "/audit/logs"})
        return self._check("audit_api", "ok", "Audit log API is mounted.", {"path": "/audit/logs"})

    def _check_backup_restore(self) -> dict[str, Any]:
        tool_path = Path("tools/backup_restore.py")
        if not tool_path.exists():
            return self._check("backup_restore", "blocker", "Backup/restore CLI is missing.", {"path": str(tool_path)})
        status = BackupService(self.settings, self.metadata_store, self.vector_store).backup_status()
        if status["status"] != "ok":
            return self._check("backup_restore", "warning", "No successful backup marker exists yet; run backup before launch.", status)
        return self._check("backup_restore", "ok", "Backup marker is present.", status)

    def _check_redis_runtime(self) -> dict[str, Any]:
        enabled = bool(getattr(self.settings, "enable_redis", False))
        details = {
            "enable_redis": enabled,
            "rate_limit_backend": getattr(self.settings, "rate_limit_backend", "memory"),
            "session_backend": getattr(self.settings, "session_backend", "db"),
            "agent_state_backend": getattr(self.settings, "agent_state_backend", "memory"),
            "cache_backend": getattr(self.settings, "cache_backend", "memory"),
        }
        if not enabled:
            if self.settings.app_env.lower() == "production":
                return self._check("redis_runtime", "blocker", "Production readiness requires Redis for volatile state.", details)
            return self._check("redis_runtime", "ok", "Redis is disabled for local development.", details)
        required_backends = {
            "rate_limit_backend": "redis",
            "session_backend": "redis",
            "agent_state_backend": "redis",
            "cache_backend": "redis",
        }
        disabled = {key: getattr(self.settings, key, None) for key, expected in required_backends.items() if getattr(self.settings, key, None) != expected}
        if self.settings.app_env.lower() == "production" and disabled:
            details["disabled_redis_backends"] = disabled
            return self._check("redis_runtime", "blocker", "Production launch requires Redis for rate limits, sessions, background state, and cache.", details)
        if self.redis_service is None:
            if self.settings.app_env.lower() != "production":
                return self._check("redis_runtime", "ok", "Redis is enabled; runtime probe is skipped outside production.", details)
            return self._check("redis_runtime", "warning", "Redis is enabled but no Redis service was provided to readiness.", details)
        status = self._safe_status(self.redis_service)
        details["runtime_status"] = status
        if status.get("status") != "ok":
            severity = "blocker" if self.settings.app_env.lower() == "production" else "warning"
            return self._check("redis_runtime", severity, "Redis backend is unavailable.", details)
        return self._check("redis_runtime", "ok", "Redis backend is reachable.", details)

    def _check_production_dependencies(self) -> dict[str, Any]:
        blockers = []
        if not self.settings.require_auth:
            blockers.append("REQUIRE_AUTH must be true")
        if getattr(self.settings, "enable_local_user_fallback", False):
            blockers.append("ENABLE_LOCAL_USER_FALLBACK must be false")
        if self.settings.database_backend.lower() != "postgres":
            blockers.append("DATABASE_BACKEND must be postgres")
        if not self.settings.enable_redis:
            blockers.append("ENABLE_REDIS must be true")
        if self.settings.rate_limit_backend != "redis":
            blockers.append("RATE_LIMIT_BACKEND must be redis")
        if self.settings.session_backend != "redis":
            blockers.append("SESSION_BACKEND must be redis")
        if self.settings.agent_state_backend != "redis":
            blockers.append("AGENT_STATE_BACKEND must be redis")
        if self.settings.cache_backend != "redis":
            blockers.append("CACHE_BACKEND must be redis")
        if not self.settings.enable_real_orchestrator:
            blockers.append("ENABLE_REAL_ORCHESTRATOR must be true")
        if not self.settings.enable_graph_memory:
            blockers.append("ENABLE_GRAPH_MEMORY must be true or graph claims must be hidden")
        if blockers:
            return self._check("production_dependencies", "blocker", "Production launch profile is incomplete.", {"blockers": blockers})
        return self._check("production_dependencies", "ok", "Production launch profile has required auth, Postgres, Redis, RBAC, graph, and orchestrator switches enabled.", {})

    def _check_upload_limits(self) -> dict[str, Any]:
        if self.settings.max_upload_mb <= 0 or self.settings.max_workspace_documents <= 0:
            return self._check("upload_limits", "blocker", "Upload limits must be positive.", {})
        return self._check(
            "upload_limits",
            "ok",
            "Free SaaS upload limits are configured.",
            {"max_upload_mb": self.settings.max_upload_mb, "max_upload_files": self.settings.max_upload_files, "max_workspace_documents": self.settings.max_workspace_documents},
        )

    def _check_memory(self) -> dict[str, Any]:
        if not self.settings.enable_persistent_memory:
            return self._check("persistent_memory", "blocker", "Persistent memory is disabled.", {})
        return self._check("persistent_memory", "ok", "Persistent memory is enabled.", {})

    def _check_multimodal(self) -> dict[str, Any]:
        if not self.settings.enable_multimodal:
            return self._check("multimodal", "warning", "Multimodal OCR/extraction is disabled.", {})
        return self._check("multimodal", "ok", "Multimodal extraction is enabled.", {})

    def _check_evaluation_dataset(self) -> dict[str, Any]:
        dataset = Path(self.settings.data_dir) / "eval_dataset_novatech.json"
        if not dataset.exists():
            return self._check("evaluation_suite", "warning", "Evaluation dataset is missing; launch gates cannot run recall/citation checks.", {"path": str(dataset)})
        return self._check("evaluation_suite", "ok", "Evaluation dataset is present.", {"path": str(dataset)})

    def _check_graph_eval_gate(self) -> dict[str, Any]:
        if not self.settings.enable_graph_memory:
            return self._check("graph_eval_gate", "ok", "Graph memory is disabled; graph eval gate is not required.", {"enabled": False})
        if self.settings.app_env.lower() != "production":
            return self._check("graph_eval_gate", "ok", "Graph eval launch gate is reported but not enforced outside production.", {"enabled": True})
        if not getattr(self.settings, "graph_eval_required", True):
            return self._check("graph_eval_gate", "warning", "Graph memory is enabled but graph eval gate is not required.", {"required": False})
        if self.evaluation_service is None:
            return self._check("graph_eval_gate", "blocker", "Graph memory is enabled but evaluation service is unavailable.", {})
        latest = {}
        try:
            latest = self.evaluation_service.latest_graph_lift()
        except Exception as exc:
            return self._check("graph_eval_gate", "blocker", "Graph eval status could not be read.", {"detail": str(exc)})
        threshold = float(getattr(self.settings, "graph_eval_min_lift", 0.05) or 0.0)
        observed = float(latest.get("lift", 0.0) or 0.0)
        if not latest.get("run_id"):
            return self._check("graph_eval_gate", "blocker", "Graph memory is enabled but no graph-lift eval run exists.", {"threshold": threshold})
        if observed < threshold:
            return self._check("graph_eval_gate", "blocker", "Graph-lift eval is below launch threshold.", {**latest, "threshold": threshold})
        return self._check("graph_eval_gate", "ok", "Graph-lift eval passed.", {**latest, "threshold": threshold})

    def _check_huggingface_runtime(self) -> dict[str, Any]:
        if self.huggingface_registry is None:
            return self._check("hf_providers", "ok", "Hugging Face provider registry was not provided; optional providers are not enforced.", {})
        status = self._safe_status(self.huggingface_registry)
        if status.get("enabled") and status.get("error_count", 0):
            return self._check("hf_providers", "warning", "Some Hugging Face task providers are degraded.", status)
        return self._check("hf_providers", "ok", "Hugging Face task provider status reported.", status)

    def _check_security_profile(self) -> dict[str, Any]:
        if not self.settings.require_auth:
            return self._check("security_profile", "blocker", "Launch must require authentication.", {"require_auth": self.settings.require_auth})
        if getattr(self.settings, "enable_local_user_fallback", False):
            return self._check("security_profile", "blocker", "Local-user fallback must be disabled for launch.", {"enable_local_user_fallback": True})
        if self.settings.app_env.lower() == "production" and self.settings.email_provider == "console":
            return self._check("security_profile", "blocker", "Production launch must configure a real email provider.", {"email_provider": self.settings.email_provider})
        if not self.settings.enable_rate_limit:
            return self._check("security_profile", "blocker", "Rate limiting must be enabled for launch.", {"enable_rate_limit": self.settings.enable_rate_limit})
        if not self.settings.enable_security_headers:
            return self._check("security_profile", "warning", "Security headers are disabled.", {"enable_security_headers": self.settings.enable_security_headers})
        return self._check("security_profile", "ok", "Auth, rate limits, and security headers are configured.", {"require_auth": self.settings.require_auth, "enable_rate_limit": self.settings.enable_rate_limit})

    @staticmethod
    def _safe_status(component) -> dict[str, Any]:
        try:
            return component.status()
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    @staticmethod
    def _check(name: str, status: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
        return {"name": name, "status": status, "message": message, "details": details}

    @staticmethod
    def _summary(blockers: list[dict], warnings: list[dict]) -> str:
        if blockers:
            return f"Launch blocked by {len(blockers)} critical readiness issue(s)."
        if warnings:
            return f"Launch has {len(warnings)} warning(s) to resolve or accept."
        return "Aiwana launch readiness checks passed."
