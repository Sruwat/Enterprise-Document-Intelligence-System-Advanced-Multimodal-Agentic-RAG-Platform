from __future__ import annotations

import json
import sys
import argparse
import socket
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.core.dependencies import get_evaluation_service, get_metadata_store, get_vector_store
from app.services.launch_doctor import LaunchDoctor


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Aiwana launch readiness checks.")
    parser.add_argument("--include-frontend", action="store_true", help="Run the Next.js production build as a launch gate.")
    parser.add_argument("--include-evals", action="store_true", help="Require seeded evaluation gates to meet launch thresholds.")
    parser.add_argument("--production", action="store_true", help="Require production storage/security profile gates.")
    args = parser.parse_args()
    settings = get_settings()
    preflight = _database_socket_preflight(settings)
    if preflight is not None:
        print(json.dumps(preflight, indent=2))
        raise SystemExit(1)
    try:
        metadata_store = get_metadata_store()
        vector_store = get_vector_store()
        evaluation_service = get_evaluation_service() if args.include_evals or args.production else None
    except Exception as exc:
        report = {
            "status": "blocked",
            "blocker_count": 1,
            "warning_count": 0,
            "checks": [
                {
                    "name": "runtime_dependencies",
                    "status": "blocker",
                    "message": "Launch doctor could not initialize runtime dependencies.",
                    "details": {"error": str(exc), "hint": "Install requirements and start Postgres/Redis/Qdrant before running production launch checks."},
                }
            ],
            "summary": "Launch blocked by 1 critical readiness issue(s).",
            "next_commands": ["pip install -r requirements-backend.txt", "docker compose -f docker-compose.prod.yml up --build"],
        }
    else:
        report = LaunchDoctor(
            settings,
            metadata_store,
            vector_store,
            evaluation_service,
            include_frontend=args.include_frontend or args.production,
            include_production=args.production,
            include_evals=args.include_evals,
        ).report()
    print(json.dumps(report, indent=2))
    if report["status"] == "blocked":
        raise SystemExit(1)


def _database_socket_preflight(settings) -> dict | None:
    if str(getattr(settings, "database_backend", "")).lower() != "postgres":
        return None
    parsed = urlparse(str(settings.database_url).replace("postgresql+psycopg://", "postgresql://"))
    host = parsed.hostname or "localhost"
    port = int(parsed.port or 5432)
    try:
        with socket.create_connection((host, port), timeout=3):
            return None
    except Exception as exc:
        return {
            "status": "blocked",
            "blocker_count": 1,
            "warning_count": 0,
            "checks": [
                {
                    "name": "postgres_socket",
                    "status": "blocker",
                    "message": "Postgres is not reachable before repository initialization.",
                    "details": {"host": host, "port": port, "error": str(exc)},
                }
            ],
            "summary": "Launch blocked by 1 critical readiness issue(s).",
            "next_commands": ["docker compose up -d postgres redis qdrant", "powershell -ExecutionPolicy Bypass -File tools/run_local_prod.ps1"],
        }


if __name__ == "__main__":
    main()
