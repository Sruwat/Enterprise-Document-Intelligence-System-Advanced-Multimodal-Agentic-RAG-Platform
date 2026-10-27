import sqlite3

from app.core.config import Settings
from app.services.backup import BackupService
from app.storage.metadata_store import MetadataStore


class _VectorStore:
    collection_name = "aiwana_chunks_v2"

    def collection_report(self):
        return {"collection": self.collection_name, "points_count": 0, "named_vectors": ["text_dense", "visual_dense", "table_dense"]}


def _settings(tmp_path):
    return Settings(
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
        BACKUP_DIR=str(tmp_path / "backups"),
        GROQ_API_KEY="key",
    )


def test_backup_creates_restorable_bundle(tmp_path):
    settings = _settings(tmp_path)
    store = MetadataStore(settings.metadata_db)
    service = BackupService(settings, store, _VectorStore())

    result = service.create_backup(tmp_path / "backups" / "smoke")

    assert result["status"] == "ok"
    backup_dir = tmp_path / "backups" / "smoke"
    assert (backup_dir / "metadata.db").exists()
    assert (backup_dir / "backup_manifest.json").exists()
    assert (backup_dir / "qdrant_manifest.json").exists()
    assert service.validate_restore(backup_dir)["status"] == "ok"


def test_restore_dry_run_blocks_invalid_schema(tmp_path):
    settings = _settings(tmp_path)
    store = MetadataStore(settings.metadata_db)
    backup_dir = tmp_path / "broken"
    backup_dir.mkdir()
    sqlite3.connect(backup_dir / "metadata.db").close()

    result = BackupService(settings, store, _VectorStore()).restore(backup_dir, dry_run=True)

    assert result["status"] == "blocked"
    assert any("missing required tables" in error for error in result["errors"])
