# Backup And Restore

Back up in this order:

1. PostgreSQL metadata.
2. Qdrant vectors or snapshots.
3. Object/file storage.
4. Configuration and model/version manifest.

Restore in this order:

1. Restore Postgres.
2. Restore object/file storage.
3. Restore Qdrant collection/snapshot.
4. Run migrations.
5. Run launch doctor and smoke tests.
6. Run a seeded authenticated query.

Use existing tools:

```powershell
python tools\backup_restore.py
python tools\qdrant_snapshot.py
python tools\launch_doctor.py
python tools\smoke_prod.py
```

Do not overwrite production data during a restore drill. Restore into a separate database/collection first and verify integrity.

