from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REQUIRED_TABLES = {
    "users",
    "tenants",
    "workspaces",
    "documents",
    "chunks",
    "chat_sessions",
    "chat_messages",
    "memory_records",
    "api_keys",
    "agent_runs",
    "audit_logs",
    "evidence_anchors",
    "extracted_artifacts",
}


class BackupService:
    def __init__(self, settings, metadata_store, vector_store=None) -> None:
        self.settings = settings
        self.metadata_store = metadata_store
        self.vector_store = vector_store

    def create_backup(self, output_dir: str | Path | None = None) -> dict[str, Any]:
        target = Path(output_dir or self.settings.backup_dir / f"backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}")
        target.mkdir(parents=True, exist_ok=True)
        active_db_path = Path(getattr(self.metadata_store, "db_path", ""))
        if active_db_path.exists():
            db_backup = target / "metadata.db"
            self._backup_sqlite(active_db_path, db_backup)
            db_schema = self._inspect_sqlite(db_backup)
        elif str(getattr(self.settings, "database_backend", "sqlite")).lower() == "postgres":
            db_backup = target / "metadata.sql"
            db_schema = self._backup_postgres(str(self.settings.database_url), db_backup)
        else:
            db_backup = target / "metadata.db"
            self._backup_sqlite(active_db_path, db_backup)
            db_schema = self._inspect_sqlite(db_backup)
        migration_state = self._copy_if_exists(Path(self.settings.data_dir) / "aiwana_migration_state.json", target / "aiwana_migration_state.json")
        previews_manifest = self._write_previews_manifest(target / "previews_manifest.json")
        qdrant_manifest = self._write_qdrant_manifest(target / "qdrant_manifest.json")
        manifest = {
            "backup_id": str(uuid.uuid4()),
            "created_at": datetime.utcnow().isoformat(),
            "metadata_db": str(db_backup),
            "database_backend": self.settings.database_backend,
            "migration_state": str(migration_state) if migration_state else None,
            "previews_manifest": str(previews_manifest),
            "qdrant_manifest": str(qdrant_manifest),
            "schema": db_schema,
        }
        manifest_path = target / "backup_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
        self._write_latest_marker(target, manifest)
        return {"status": "ok", "backup_dir": str(target), "manifest": manifest}

    def validate_restore(self, input_dir: str | Path) -> dict[str, Any]:
        source = Path(input_dir)
        manifest_path = source / "backup_manifest.json"
        db_path = source / "metadata.db"
        errors: list[str] = []
        warnings: list[str] = []
        if not source.exists():
            errors.append(f"Backup directory does not exist: {source}")
        if not manifest_path.exists():
            errors.append("backup_manifest.json is missing.")
        if not db_path.exists():
            errors.append("metadata.db is missing.")
        schema = self._inspect_sqlite(db_path) if db_path.exists() else {"tables": []}
        missing_tables = sorted(REQUIRED_TABLES - set(schema.get("tables", [])))
        if missing_tables:
            errors.append(f"Backup metadata DB is missing required tables: {', '.join(missing_tables)}")
        qdrant_manifest = source / "qdrant_manifest.json"
        if not qdrant_manifest.exists():
            warnings.append("qdrant_manifest.json is missing; vector restore compatibility cannot be confirmed.")
        elif self.vector_store is not None:
            try:
                payload = json.loads(qdrant_manifest.read_text(encoding="utf-8"))
                active = getattr(self.vector_store, "collection_name", None)
                if active and payload.get("collection") and payload["collection"] != active:
                    errors.append(f"Qdrant collection mismatch: backup={payload['collection']} active={active}")
                snapshot_name = payload.get("snapshot_name")
                if snapshot_name:
                    snapshot_status = self._snapshot_exists(snapshot_name)
                    if snapshot_status.get("status") == "missing":
                        errors.append(f"Qdrant snapshot is not available on the active server: {snapshot_name}")
                    elif snapshot_status.get("status") == "unknown":
                        warnings.append(f"Qdrant snapshot availability could not be confirmed: {snapshot_name}")
            except json.JSONDecodeError:
                errors.append("qdrant_manifest.json is invalid JSON.")
        return {
            "status": "blocked" if errors else "ok",
            "errors": errors,
            "warnings": warnings,
            "schema": schema,
            "restore_requires_confirm": True,
        }

    def restore(self, input_dir: str | Path, *, confirm: bool = False, dry_run: bool = True) -> dict[str, Any]:
        validation = self.validate_restore(input_dir)
        if validation["status"] != "ok" or dry_run:
            return {"status": validation["status"], "dry_run": True, **validation}
        if not confirm:
            return {"status": "blocked", "errors": ["Restore requires --confirm."], "warnings": validation["warnings"]}
        source_db = Path(input_dir) / "metadata.db"
        self._backup_sqlite(source_db, Path(self.metadata_store.db_path))
        return {"status": "ok", "dry_run": False, "restored_metadata_db": str(self.metadata_store.db_path)}

    def backup_status(self) -> dict[str, Any]:
        marker = Path(self.settings.backup_dir) / "latest_backup.json"
        if not marker.exists():
            return {"status": "missing", "path": str(marker)}
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"status": "invalid", "path": str(marker)}
        backup_dir = Path(payload.get("backup_dir", ""))
        return {"status": "ok" if backup_dir.exists() else "missing", "path": str(marker), "backup_dir": str(backup_dir), "created_at": payload.get("created_at")}

    @staticmethod
    def _backup_sqlite(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
            src.backup(dst)

    def _backup_postgres(self, database_url: str, destination: Path) -> dict[str, Any]:
        destination.parent.mkdir(parents=True, exist_ok=True)
        pg_dump = shutil.which("pg_dump")
        if pg_dump:
            result = subprocess.run(
                [pg_dump, "--format=plain", "--no-owner", "--no-acl", "--file", str(destination), database_url],
                check=False,
                capture_output=True,
                text=True,
            )
        else:
            result = self._backup_postgres_from_docker(database_url, destination)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else str(result.stderr or "")
            stdout = result.stdout.decode("utf-8", errors="replace") if isinstance(result.stdout, bytes) else str(result.stdout or "")
            raise RuntimeError(f"pg_dump failed: {stderr.strip() or stdout.strip()}")
        table_counts = {}
        counter = getattr(self.metadata_store, "table_counts", None)
        if callable(counter):
            table_counts = counter()
        return {"dump": str(destination), "counts": table_counts}

    @staticmethod
    def _backup_postgres_from_docker(database_url: str, destination: Path) -> subprocess.CompletedProcess:
        docker = shutil.which("docker")
        if not docker:
            raise RuntimeError("pg_dump is required for Postgres backups, and Docker was not found for container fallback.")
        parsed = urlparse(database_url.replace("postgresql+psycopg://", "postgresql://"))
        user = parsed.username or "aiwana"
        password = parsed.password or ""
        database = parsed.path.lstrip("/") or "aiwana"
        container = "aiwana-postgres"
        result = subprocess.run(
            [docker, "exec", "-e", f"PGPASSWORD={password}", container, "pg_dump", "-U", user, "-d", database, "--format=plain", "--no-owner", "--no-acl"],
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            destination.write_bytes(result.stdout)
        return result

    @staticmethod
    def _inspect_sqlite(db_path: Path) -> dict[str, Any]:
        if not db_path.exists():
            return {"tables": []}
        with sqlite3.connect(db_path) as conn:
            tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
            counts = {}
            for table in tables:
                try:
                    counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                except sqlite3.Error:
                    counts[table] = None
        return {"tables": tables, "counts": counts}

    @staticmethod
    def _copy_if_exists(source: Path, destination: Path) -> Path | None:
        if not source.exists():
            return None
        destination.write_bytes(source.read_bytes())
        return destination

    def _write_previews_manifest(self, path: Path) -> Path:
        preview_root = Path(self.settings.data_dir) / "previews"
        files = []
        if preview_root.exists():
            for item in preview_root.rglob("*"):
                if item.is_file():
                    files.append({"path": str(item), "size": item.stat().st_size})
        path.write_text(json.dumps({"preview_root": str(preview_root), "files": files}, indent=2), encoding="utf-8")
        return path

    def _write_qdrant_manifest(self, path: Path) -> Path:
        payload: dict[str, Any] = {
            "collection": getattr(self.vector_store, "collection_name", self.settings.qdrant_collection),
            "snapshot_created": False,
            "snapshot_warning": "Qdrant snapshot API was not invoked; manifest records collection compatibility metadata.",
        }
        if self.vector_store is not None:
            reporter = getattr(self.vector_store, "collection_report", None)
            if callable(reporter):
                payload.update(reporter())
            snapshots = getattr(self.vector_store, "list_snapshots", None)
            if callable(snapshots):
                snapshot_report = snapshots()
                payload["snapshots"] = snapshot_report.get("snapshots", [])
                payload["snapshot_list_status"] = snapshot_report.get("status")
                latest_snapshot = self._latest_snapshot(payload["snapshots"])
                payload["snapshot_name"] = latest_snapshot.get("name") if latest_snapshot else None
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    def _snapshot_exists(self, snapshot_name: str) -> dict[str, str]:
        snapshots = getattr(self.vector_store, "list_snapshots", None)
        if not callable(snapshots):
            return {"status": "unknown"}
        snapshot_report = snapshots()
        if snapshot_report.get("status") != "ok":
            return {"status": "unknown"}
        names = {snapshot.get("name") for snapshot in snapshot_report.get("snapshots", []) if isinstance(snapshot, dict)}
        return {"status": "ok" if snapshot_name in names else "missing"}

    @staticmethod
    def _latest_snapshot(snapshots: list[dict[str, Any]]) -> dict[str, Any] | None:
        named = [snapshot for snapshot in snapshots if isinstance(snapshot, dict) and snapshot.get("name")]
        if not named:
            return None
        return sorted(named, key=lambda snapshot: str(snapshot.get("creation_time") or snapshot.get("name")), reverse=True)[0]

    def _write_latest_marker(self, backup_dir: Path, manifest: dict[str, Any]) -> None:
        marker = Path(self.settings.backup_dir) / "latest_backup.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps({"backup_dir": str(backup_dir), "created_at": manifest["created_at"], "backup_id": manifest["backup_id"]}, indent=2),
            encoding="utf-8",
        )
