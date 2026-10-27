# Aiwana Backup And Restore Drill

1. Run `python tools/backup_restore.py backup`.
2. Confirm `data/backups/latest` contains metadata and vector snapshot artifacts.
3. Restore into a clean staging environment.
4. Run `/health`, `/readiness/launch`, and seeded evals.
5. Verify counts for users, workspaces, documents, chunks, query logs, artifacts, graph tables, and audit logs.
6. Record the restore timestamp and any blocker before production launch.
