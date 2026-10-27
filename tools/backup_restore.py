from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.dependencies import get_app_settings, get_metadata_store, get_vector_store
from app.services.backup import BackupService


def main() -> None:
    args = _parse_args()
    service = BackupService(get_app_settings(), get_metadata_store(), get_vector_store())
    if args.command == "backup":
        result = service.create_backup(args.output)
    elif args.command == "restore":
        result = service.restore(args.input, confirm=args.confirm, dry_run=args.dry_run)
    else:
        raise SystemExit(f"Unknown command: {args.command}")
    print(json.dumps(result, indent=2, default=str))
    if result.get("status") == "blocked":
        raise SystemExit(1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backup or validate/restore Aiwana metadata and vector-store launch metadata.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup", help="Create a backup bundle.")
    backup.add_argument("--output", required=True, help="Directory where the backup bundle should be written.")
    restore = subparsers.add_parser("restore", help="Validate or restore a backup bundle.")
    restore.add_argument("--input", required=True, help="Backup directory to validate or restore.")
    restore.add_argument("--dry-run", action="store_true", help="Validate only. No files are restored.")
    restore.add_argument("--confirm", action="store_true", help="Required for non-dry-run restore.")
    return parser.parse_args()


if __name__ == "__main__":
    main()
