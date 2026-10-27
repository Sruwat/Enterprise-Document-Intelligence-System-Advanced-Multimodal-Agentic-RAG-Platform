from __future__ import annotations

import subprocess
import shutil
import sys
from pathlib import Path
from typing import Any

from app.services.backup import BackupService
from app.services.redis_client import RedisService


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class LaunchDoctor:
    def __init__(
        self,
        settings,
        metadata_store=None,
        vector_store=None,
        evaluation_service=None,
        *,
        include_frontend: bool = False,
        include_production: bool = False,
        include_evals: bool = False,
        project_root: Path | None = None,
    ) -> None:
        self.settings = settings
        self.metadata_store = metadata_store
        self.vector_store = vector_store
        self.evaluation_service = evaluation_service
        self.include_frontend = include_frontend
        self.include_production = include_production
        self.include_evals = include_evals or include_production
        self.project_root = project_root or PROJECT_ROOT

    def report(self) -> dict[str, Any]:
        checks = [
            self._check_env_profile(),
            self._check_database_profile(),
            self._check_redis_profile(),
            self._check_graph_profile(),
            self._check_model_assets(),
            self._check_llm(),
            self._check_qdrant_profile(),
            self._check_qdrant_schema(),
            self._check_qdrant_filters(),
            self._check_documents(),
            self._check_capability_gates(),
            self._check_backup_restore(),
            self._check_audit_route(),
        ]
        if self.include_frontend:
            checks.append(self._check_frontend_build())
        if self.include_evals:
            checks.append(self._check_evaluation_gates())
        blockers = [check for check in checks if check["status"] == "blocker"]
        warnings = [check for check in checks if check["status"] == "warning"]
        return {
            "status": "blocked" if blockers else "warning" if warnings else "ready",
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
            "checks": checks,
            "summary": self._summary(blockers, warnings),
            "next_commands": self._next_commands(checks),
        }

    def _check_env_profile(self) -> dict[str, Any]:
        issues: list[str] = []
        if "bge-m3" not in self.settings.embedding_model.lower():
            issues.append("EMBEDDING_MODEL must be BAAI/bge-m3")
        if "aiwana_chunks_v2" != self.settings.qdrant_collection:
            issues.append("QDRANT_COLLECTION must be aiwana_chunks_v2")
        if not self.settings.enable_named_vectors:
            issues.append("ENABLE_NAMED_VECTORS must be true")
        if not self.settings.enable_persistent_memory:
            issues.append("ENABLE_PERSISTENT_MEMORY must be true")
        if issues:
            return self._check("env_profile", "blocker", "; ".join(issues), self._profile_details())
        return self._check("env_profile", "ok", "Launch environment profile is configured.", self._profile_details())

    def _check_database_profile(self) -> dict[str, Any]:
        backend = str(getattr(self.settings, "database_backend", "sqlite")).lower()
        details = {
            "database_backend": backend,
            "database_url_configured": bool(getattr(self.settings, "database_url", "")),
            "sqlite_fallback": bool(getattr(self.settings, "enable_sqlite_fallback", True)),
        }
        if self.include_production and backend != "postgres":
            return self._check("database_profile", "blocker", "Production launch must use PostgreSQL.", details)
        if backend == "postgres" and not details["database_url_configured"]:
            return self._check("database_profile", "blocker", "DATABASE_URL is required when DATABASE_BACKEND=postgres.", details)
        return self._check("database_profile", "ok", f"Database backend is {backend}.", details)

    def _check_redis_profile(self) -> dict[str, Any]:
        enabled = bool(getattr(self.settings, "enable_redis", False))
        details = {
            "enable_redis": enabled,
            "redis_url_configured": bool(getattr(self.settings, "redis_url", "")),
            "rate_limit_backend": getattr(self.settings, "rate_limit_backend", "memory"),
            "session_backend": getattr(self.settings, "session_backend", "db"),
            "agent_state_backend": getattr(self.settings, "agent_state_backend", "memory"),
        }
        if self.include_production and not enabled:
            return self._check("redis_profile", "blocker", "Production launch must enable Redis-backed volatile state.", details)
        if enabled and not details["redis_url_configured"]:
            return self._check("redis_profile", "blocker", "REDIS_URL is required when ENABLE_REDIS=true.", details)
        if enabled:
            status = RedisService(self.settings.redis_url, enabled=True).status()
            details["runtime_status"] = status
            if self.include_production and status.get("status") != "ok":
                return self._check("redis_profile", "blocker", "Production Redis backend is unavailable.", details)
            if status.get("status") != "ok":
                return self._check("redis_profile", "warning", "Redis is enabled but unavailable; volatile state will not be distributed.", details)
        return self._check("redis_profile", "ok", "Redis profile is configured for the selected environment.", details)

    def _check_graph_profile(self) -> dict[str, Any]:
        enabled = bool(getattr(self.settings, "enable_graph_memory", False))
        backend = str(getattr(self.settings, "graph_backend", "postgres")).lower()
        database_backend = str(getattr(self.settings, "database_backend", "sqlite")).lower()
        details = {"enable_graph_memory": enabled, "graph_backend": backend, "database_backend": database_backend}
        if not enabled:
            return self._check("graph_profile", "ok", "Graph memory is disabled for this profile.", details)
        if backend != "postgres":
            return self._check("graph_profile", "blocker", "Graph memory currently supports GRAPH_BACKEND=postgres.", details)
        if database_backend != "postgres":
            severity = "blocker" if self.include_production else "warning"
            return self._check("graph_profile", severity, "Graph memory requires DATABASE_BACKEND=postgres so graph facts share durable metadata.", details)
        return self._check("graph_profile", "ok", "Postgres graph memory profile is configured.", details)

    def _check_model_assets(self) -> dict[str, Any]:
        embedding_path = Path(self.settings.embedding_model_path)
        reranker_path = Path(self.settings.reranker_model_path)
        missing = []
        if "bge-m3" not in self.settings.embedding_model.lower():
            missing.append("embedding model is not BAAI/bge-m3")
        if "v2-m3" not in str(self.settings.reranker_model).lower() and "v2-m3" not in str(reranker_path).lower():
            missing.append("reranker model is not BAAI/bge-reranker-v2-m3")
        if not self._has_model_files(embedding_path):
            missing.append(f"missing embedding model files at {embedding_path}")
        if not self._has_model_files(reranker_path):
            missing.append(f"missing reranker model files at {reranker_path}")
        if missing:
            return self._check("model_assets", "blocker", "; ".join(missing), {"embedding_path": str(embedding_path), "reranker_path": str(reranker_path)})
        return self._check("model_assets", "ok", "BGE-M3 and reranker model folders exist.", {"embedding_path": str(embedding_path), "reranker_path": str(reranker_path)})

    def _check_llm(self) -> dict[str, Any]:
        provider = str(getattr(self.settings, "llm_provider", "groq")).lower()
        privacy_mode = str(getattr(self.settings, "llm_privacy_mode", "external_allowed")).lower()
        details = {"llm_provider": provider, "llm_model": self.settings.llm_model, "privacy_mode": privacy_mode}
        if privacy_mode == "private_only" and provider not in {"openai_compatible", "private", "ollama"}:
            return self._check("llm", "blocker", "Private-only mode cannot use a public LLM provider.", details)
        if provider == "groq" and not self.settings.groq_api_key:
            return self._check("llm", "blocker", "GROQ_API_KEY is empty.", {"llm_provider": self.settings.llm_provider})
        if provider == "openai" and not self.settings.openai_api_key:
            return self._check("llm", "blocker", "OPENAI_API_KEY is empty.", details)
        if provider in {"openai_compatible", "private"} and not getattr(self.settings, "llm_base_url", ""):
            return self._check("llm", "blocker", "LLM_BASE_URL is required for private OpenAI-compatible providers.", details)
        if provider == "ollama" and not getattr(self.settings, "ollama_base_url", ""):
            return self._check("llm", "blocker", "OLLAMA_BASE_URL is required for Ollama provider.", details)
        if provider not in getattr(self.settings, "supported_llm_providers", {"groq", "openai"}):
            return self._check("llm", "blocker", f"Unsupported LLM provider: {provider}.", details)
        return self._check("llm", "ok", f"{provider} LLM provider is configured.", details)

    def _check_qdrant_profile(self) -> dict[str, Any]:
        if not str(self.settings.qdrant_url).startswith(("http://", "https://")):
            return self._check("qdrant_profile", "blocker", "QDRANT_URL must point to a Qdrant server for SaaS launch.", {"qdrant_url": self.settings.qdrant_url})
        if self.vector_store is not None and self.vector_store.is_available() and not self.vector_store.get_active_location().startswith("file://"):
            return self._check(
                "qdrant_profile",
                "ok",
                "Qdrant server is active.",
                {"qdrant_url": self.settings.qdrant_url, "active_location": self.vector_store.get_active_location(), "vector_count": self.vector_store.count()},
            )
        if str(self.settings.qdrant_local_fallback_url).startswith("file://"):
            return self._check("qdrant_profile", "warning", "Local Qdrant fallback is configured; readiness must confirm server Qdrant is active.", {"qdrant_url": self.settings.qdrant_url, "fallback": self.settings.qdrant_local_fallback_url})
        return self._check("qdrant_profile", "ok", "Qdrant server profile is configured.", {"qdrant_url": self.settings.qdrant_url})

    def _check_qdrant_schema(self) -> dict[str, Any]:
        verifier = getattr(self.vector_store, "verify_collection", None) if self.vector_store is not None else None
        if not callable(verifier):
            return self._check("qdrant_schema", "warning", "Vector store cannot report Qdrant schema.", {})
        report = verifier(1024 if "bge-m3" in self.settings.embedding_model.lower() else 384)
        if not report.get("ok"):
            location = str(report.get("location") or (self.vector_store.get_active_location() if self.vector_store else ""))
            if location.startswith("file://") and not self.include_production:
                return self._check("qdrant_schema", "warning", "Local Qdrant fallback cannot enforce payload indexes; use server Qdrant for SaaS launch.", report)
            return self._check("qdrant_schema", "blocker", "Qdrant collection is missing required vectors, sparse vectors, or payload indexes.", report)
        return self._check("qdrant_schema", "ok", "Qdrant schema includes required vectors and payload indexes.", report)

    def _check_qdrant_filters(self) -> dict[str, Any]:
        verifier = getattr(self.vector_store, "verify_server_side_filters", None) if self.vector_store is not None else None
        if not callable(verifier):
            return self._check("qdrant_filters", "warning", "Vector store cannot verify Qdrant payload filters.", {})
        report = verifier(1024 if "bge-m3" in self.settings.embedding_model.lower() else 384)
        if not report.get("ok"):
            return self._check("qdrant_filters", "blocker", "Qdrant payload filter probe failed.", report)
        if self.include_production and not report.get("server_side"):
            return self._check("qdrant_filters", "blocker", "Production launch requires server-side Qdrant filters.", report)
        status = "ok" if report.get("server_side") else "warning"
        message = "Qdrant server-side payload filter probe passed." if report.get("server_side") else "Local fallback payload filter probe passed; server Qdrant is required for production."
        return self._check("qdrant_filters", status, message, report)

    def _check_documents(self) -> dict[str, Any]:
        if self.metadata_store is None:
            return self._check("documents", "warning", "Metadata store not provided; cannot inspect existing source files.", {})
        documents = self.metadata_store.list_documents()
        existing_sources = [document for document in documents if Path(document.source_path).is_file()]
        if documents and not existing_sources:
            return self._check("documents", "blocker", "Existing document records have no readable source files to re-ingest.", {"documents": len(documents), "reingestable": 0})
        if not documents:
            return self._check("documents", "warning", "No documents are indexed yet; upload real 100-200 page launch test documents after migration.", {"documents": 0})
        return self._check("documents", "ok", "Existing source files can be re-ingested.", {"documents": len(documents), "reingestable": len(existing_sources)})

    def _check_capability_gates(self) -> dict[str, Any]:
        details = {
            "agent_orchestration": {
                "implemented": (self.project_root / "app" / "services" / "orchestrator" / "agent_orchestrator.py").exists(),
                "enabled": bool(getattr(self.settings, "enable_real_orchestrator", False)),
            },
            "legal_reasoning": {
                "implemented": (self.project_root / "app" / "services" / "agents" / "objective_agents.py").exists(),
                "clause_extractor": (self.project_root / "app" / "services" / "ingestion" / "artifact_extractor.py").exists(),
            },
            "graph_memory": {
                "implemented": (self.project_root / "app" / "services" / "graph_memory.py").exists(),
                "enabled": bool(getattr(self.settings, "enable_graph_memory", False)),
                "database_backend": getattr(self.settings, "database_backend", "sqlite"),
            },
            "research_grade_answers": {
                "implemented": True,
                "eval_category_required": "research",
            },
            "multilingual": {
                "implemented": (self.project_root / "app" / "services" / "language.py").exists(),
                "supported": ["english", "hindi", "hinglish", "spanish"],
            },
            "scanned_pdf_ocr": {
                "implemented": (self.project_root / "app" / "services" / "ingestion" / "multimodal.py").exists(),
                "enabled": bool(getattr(self.settings, "enable_multimodal", False)),
            },
        }
        blockers = []
        warnings = []
        if self.include_production and not details["agent_orchestration"]["enabled"]:
            blockers.append("ENABLE_REAL_ORCHESTRATOR=false")
        if self.include_production and not details["graph_memory"]["enabled"]:
            blockers.append("ENABLE_GRAPH_MEMORY=false")
        if details["graph_memory"]["enabled"] and str(details["graph_memory"]["database_backend"]).lower() != "postgres":
            blockers.append("graph memory requires DATABASE_BACKEND=postgres")
        if self.include_production and not details["scanned_pdf_ocr"]["enabled"]:
            warnings.append("ENABLE_MULTIMODAL=false")
        details["warnings"] = warnings
        details["blockers"] = blockers
        if blockers:
            return self._check("capability_gates", "blocker", "One or more enterprise capability gates are not production-ready.", details)
        if warnings:
            return self._check("capability_gates", "warning", "Enterprise capability code exists, but some capabilities are disabled in this profile.", details)
        return self._check("capability_gates", "ok", "Enterprise capability gates are configured.", details)

    def _check_backup_restore(self) -> dict[str, Any]:
        tool_path = self.project_root / "tools" / "backup_restore.py"
        if not tool_path.exists():
            return self._check("backup_restore", "blocker", "Backup/restore CLI is missing.", {"path": str(tool_path)})
        if self.metadata_store is None:
            return self._check("backup_restore", "warning", "Metadata store not provided; backup status cannot be inspected.", {"path": str(tool_path)})
        status = BackupService(self.settings, self.metadata_store, self.vector_store).backup_status()
        if status["status"] != "ok":
            return self._check("backup_restore", "warning", "No backup marker found yet. Run a backup before launch.", status)
        return self._check("backup_restore", "ok", "Backup/restore tooling and latest marker are present.", status)

    def _check_evaluation_gates(self) -> dict[str, Any]:
        dataset = Path(self.settings.data_dir) / "eval_dataset_aiwana_launch.json"
        if not dataset.exists():
            return self._check("evaluation_gates", "blocker", "Launch evaluation dataset is missing.", {"path": str(dataset)})
        if self.evaluation_service is None:
            return self._check("evaluation_gates", "blocker", "Evaluation service was not provided; launch eval gates cannot run.", {"path": str(dataset)})
        try:
            gates = self.evaluation_service.launch_gates(
                dataset_path=str(dataset),
                min_queries=0,
                min_citation_coverage=0.8,
                max_abstention_rate=0.4,
                min_benchmark_pass_rate=0.8,
                min_category_pass_rate=0.75,
                require_dataset_coverage=True,
            )
        except Exception as exc:
            return self._check("evaluation_gates", "blocker", "Launch evaluation gates failed to execute.", {"path": str(dataset), "error": str(exc)})
        if gates.get("status") != "ready":
            return self._check("evaluation_gates", "blocker", "Seeded evaluation gates are below launch thresholds.", gates)
        return self._check("evaluation_gates", "ok", "Seeded evaluation gates meet launch thresholds.", gates)

    def _check_audit_route(self) -> dict[str, Any]:
        try:
            from app.api.main import app

            paths = {getattr(route, "path", "") for route in app.routes}
        except Exception as exc:
            return self._check("audit_route", "blocker", "Could not inspect API routes.", {"detail": str(exc)})
        if "/audit/logs" not in paths:
            return self._check("audit_route", "blocker", "Audit log route is not mounted.", {"expected_path": "/audit/logs"})
        return self._check("audit_route", "ok", "Audit log route is mounted.", {"path": "/audit/logs"})

    def _check_frontend_build(self) -> dict[str, Any]:
        frontend_dir = self.project_root / "frontend"
        package_json = frontend_dir / "package.json"
        if not package_json.exists():
            return self._check("frontend_build", "blocker", "Frontend package.json is missing.", {"path": str(package_json)})
        try:
            completed = self._run_frontend_build(frontend_dir)
            retried_after_clean = False
            if completed.returncode != 0 and self._looks_like_stale_next_document_error(completed):
                self._clear_next_build_cache(frontend_dir)
                completed = self._run_frontend_build(frontend_dir)
                retried_after_clean = True
        except Exception as exc:
            return self._check("frontend_build", "blocker", "Frontend build could not be executed.", {"detail": str(exc)})
        details = {
            "command": "cd frontend && npm run build",
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-1200:],
            "stderr_tail": completed.stderr[-1200:],
            "retried_after_clean": retried_after_clean,
        }
        if completed.returncode != 0:
            return self._check("frontend_build", "blocker", "Frontend production build failed.", details)
        return self._check("frontend_build", "ok", "Frontend production build passes.", details)

    @staticmethod
    def _run_frontend_build(frontend_dir: Path) -> subprocess.CompletedProcess[str]:
        npm = shutil.which("npm.cmd" if sys.platform.startswith("win") else "npm") or "npm"
        return subprocess.run(
            [npm, "run", "build"],
            cwd=frontend_dir,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )

    @staticmethod
    def _looks_like_stale_next_document_error(completed: subprocess.CompletedProcess[str]) -> bool:
        output = f"{completed.stdout}\n{completed.stderr}"
        return "Cannot find module for page: /_document" in output or "PageNotFoundError" in output

    @staticmethod
    def _clear_next_build_cache(frontend_dir: Path) -> None:
        next_dir = (frontend_dir / ".next").resolve()
        expected = (frontend_dir / ".next").resolve()
        if next_dir == expected and next_dir.exists():
            shutil.rmtree(next_dir)

    def _profile_details(self) -> dict[str, Any]:
        return {
            "embedding_model": self.settings.embedding_model,
            "embedding_model_path": str(self.settings.embedding_model_path),
            "reranker_model": self.settings.reranker_model,
            "reranker_model_path": str(self.settings.reranker_model_path),
            "qdrant_collection": self.settings.qdrant_collection,
            "enable_named_vectors": self.settings.enable_named_vectors,
            "enable_persistent_memory": self.settings.enable_persistent_memory,
            "database_backend": getattr(self.settings, "database_backend", "sqlite"),
            "enable_redis": getattr(self.settings, "enable_redis", False),
            "enable_graph_memory": getattr(self.settings, "enable_graph_memory", False),
            "enable_real_orchestrator": getattr(self.settings, "enable_real_orchestrator", False),
        }

    @staticmethod
    def _has_model_files(path: Path) -> bool:
        if not path.exists() or not path.is_dir():
            return False
        return any(
            file.is_file() and file.suffix in {".bin", ".safetensors", ".pt"} and not file.name.endswith(".lock")
            for file in path.rglob("*")
        )

    @staticmethod
    def _check(name: str, status: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
        return {"name": name, "status": status, "message": message, "details": details}

    @staticmethod
    def _summary(blockers: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> str:
        if blockers:
            return f"Launch blocked by {len(blockers)} critical readiness issue(s)."
        if warnings:
            return f"Launch has {len(warnings)} warning(s) to resolve or accept."
        return "Aiwana launch readiness checks passed."

    @staticmethod
    def _next_commands(checks: list[dict[str, Any]]) -> list[str]:
        by_name = {check["name"]: check for check in checks}
        commands: list[str] = []
        if by_name.get("model_assets", {}).get("status") == "blocker":
            commands.append("python tools/download_aiwana_models.py")
        if by_name.get("env_profile", {}).get("status") == "blocker":
            commands.append("Update .env to the BGE-M3 launch profile from README.md")
        if by_name.get("env_profile", {}).get("status") == "ok" and by_name.get("model_assets", {}).get("status") == "ok":
            commands.append("python tools/migrate_aiwana_v2.py --dry-run")
            commands.append("python tools/migrate_aiwana_v2.py --reingest")
        if by_name.get("llm", {}).get("status") == "blocker":
            commands.append("Set GROQ_API_KEY in .env")
        if by_name.get("backup_restore", {}).get("status") in {"warning", "blocker"}:
            commands.append("python tools/backup_restore.py backup --output data/backups/launch-smoke")
        if by_name.get("frontend_build", {}).get("status") == "blocker":
            commands.append("cd frontend && npm run build")
        if by_name.get("evaluation_gates", {}).get("status") == "blocker":
            commands.append("python tools/run_launch_evals.py")
        return commands
