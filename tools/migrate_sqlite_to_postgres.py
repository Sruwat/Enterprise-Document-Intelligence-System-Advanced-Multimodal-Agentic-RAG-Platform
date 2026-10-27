from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import DateTime, text
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import get_settings
from app.db.base import Base, build_engine
from app.db import models  # noqa: F401


DEFAULT_TENANT_ID = "default-tenant"
DEFAULT_USER_ID = "local-user"
DEFAULT_WORKSPACE_ID = "default"

MIGRATION_ORDER = [
    "tenants",
    "users",
    "workspaces",
    "workspace_members",
    "documents",
    "chunks",
    "ingestion_jobs",
    "chat_sessions",
    "chat_messages",
    "memory_records",
    "extracted_artifacts",
    "evidence_anchors",
    "agent_runs",
    "audit_logs",
    "auth_sessions",
    "auth_action_tokens",
    "query_logs",
    "evaluation_runs",
]

EXTRA_TARGET_TABLES = [
    "user_preferences",
    "roles",
]

CONFLICT_COLUMNS = {
    "auth_action_tokens": "token_hash",
    "auth_sessions": "session_token_hash",
    "user_preferences": "user_id",
}

VALIDATED_TARGET_TABLES = MIGRATION_ORDER + EXTRA_TARGET_TABLES


def main() -> None:
    args = _parse_args()
    settings = get_settings()
    sqlite_path = _sqlite_path(settings.sqlite_database_url, settings.metadata_db)
    source = _read_sqlite(sqlite_path)
    source_counts = {table: len(rows) for table, rows in source.items()}
    expected_counts = _expected_target_counts(source)
    report: dict[str, Any] = {
        "sqlite_db": str(sqlite_path),
        "database_url": _redact_url(settings.database_url),
        "source_counts": source_counts,
        "expected_target_counts": expected_counts,
        "tables": MIGRATION_ORDER,
        "dry_run": args.dry_run,
    }
    if args.dry_run:
        print(json.dumps({"status": "ok", **report}, indent=2, default=str))
        return
    engine = build_engine(settings.database_url)
    Base.metadata.create_all(engine)
    inserted = _apply(engine, source)
    target_counts = _target_counts(engine)
    validation = _validate_counts(expected_counts, target_counts)
    status = "ok" if validation["ok"] else "blocked"
    print(
        json.dumps(
            {"status": status, **report, "applied": inserted, "target_counts": target_counts, "validation": validation},
            indent=2,
            default=str,
        )
    )
    if not validation["ok"]:
        raise SystemExit(1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate Aiwana SQLite metadata into the production PostgreSQL schema.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Inspect source counts without writing to Postgres.")
    mode.add_argument("--apply", action="store_true", help="Create schema and copy supported records to Postgres.")
    return parser.parse_args()


def _sqlite_path(sqlite_url: str, fallback: Path) -> Path:
    if sqlite_url.startswith("sqlite:///"):
        return Path(sqlite_url.removeprefix("sqlite:///"))
    return Path(fallback)


def _read_sqlite(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        raise SystemExit(f"SQLite metadata DB does not exist: {path}")
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table}").fetchall()] if table in existing else []
            for table in MIGRATION_ORDER
        }


def _apply(engine, source: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    workspace_tenant = {row["workspace_id"]: row.get("tenant_id") or DEFAULT_TENANT_ID for row in source.get("workspaces", [])}
    inserted: dict[str, int] = {}
    with engine.begin() as conn:
        references = _build_reference_rows(source)
        for row in references["tenants"]:
            _exec(conn, "tenants", row)
        inserted["tenants"] = len(references["tenants"])
        for row in source.get("users", []):
            prefs = _json(row, "preferences_json")
            _exec(
                conn,
                "users",
                {
                    "id": row["user_id"],
                    "tenant_id": row.get("tenant_id") or DEFAULT_TENANT_ID,
                    "email": row["email"],
                    "display_name": row.get("display_name"),
                    "password_hash": prefs.get("password_hash"),
                    "password_salt": prefs.get("password_salt"),
                    "email_verified": bool(prefs.get("email_verified")),
                    "status": "active",
                    "metadata_json": {k: v for k, v in prefs.items() if k not in {"password_hash", "password_salt", "email_verified"}},
                    "created_at": row["created_at"],
                    "updated_at": row.get("updated_at"),
                },
            )
            _exec(
                conn,
                "user_preferences",
                {
                    "user_id": row["user_id"],
                    "response_language": prefs.get("preferred_response_language", "auto"),
                    "ui_language": prefs.get("preferred_ui_language", "english"),
                    "default_objective": prefs.get("default_objective", "general"),
                    "metadata_json": prefs,
                },
            )
        for row in _synthetic_users(source):
            _exec(conn, "users", row)
            _exec(
                conn,
                "user_preferences",
                {
                    "user_id": row["id"],
                    "response_language": "auto",
                    "ui_language": "english",
                    "default_objective": "general",
                    "metadata_json": {"created_by": "migration", "synthetic": True},
                },
            )
        inserted["users"] = len(source.get("users", [])) + len(_synthetic_users(source))
        for row in source.get("workspaces", []):
            _exec(conn, "workspaces", {"id": row["workspace_id"], "tenant_id": row.get("tenant_id") or DEFAULT_TENANT_ID, "owner_id": row.get("owner_id") or DEFAULT_USER_ID, "name": row["name"], "private_mode": bool(row.get("private_mode")), "external_ai_allowed": bool(row.get("external_ai_allowed")), "metadata_json": _json(row, "metadata_json"), "created_at": row["created_at"], "updated_at": row.get("updated_at")})
        inserted["workspaces"] = len(source.get("workspaces", []))
        workspace_members = _workspace_members(source)
        for row in workspace_members:
            _exec_role(conn, row["tenant_id"], row["role"])
            _exec_workspace_member(conn, row["workspace_id"], row["user_id"], row["tenant_id"], row["role"])
        inserted["workspace_members"] = len(workspace_members)
        for row in source.get("documents", []):
            workspace_id = row.get("workspace_id") or DEFAULT_WORKSPACE_ID
            _exec(conn, "documents", {"id": row["document_id"], "tenant_id": workspace_tenant.get(workspace_id, DEFAULT_TENANT_ID), "workspace_id": workspace_id, "filename": row["filename"], "source_uri": row["source_path"], "fingerprint": row.get("fingerprint"), "status": row.get("status") or "processing", "page_count": row.get("page_count") or 0, "metadata_json": _json(row, "metadata_json"), "created_at": row["ingested_at"], "updated_at": row.get("updated_at")})
        inserted["documents"] = len(source.get("documents", []))
        for row in source.get("chunks", []):
            workspace_id = row.get("workspace_id") or DEFAULT_WORKSPACE_ID
            _exec(conn, "chunks", {"id": row["chunk_id"], "tenant_id": workspace_tenant.get(workspace_id, DEFAULT_TENANT_ID), "workspace_id": workspace_id, "document_id": row["document_id"], "filename": row["filename"], "page_number": row["page_number"], "text": row["text"], "section": row.get("section"), "token_count": row.get("token_count") or 0, "metadata_json": _json(row, "metadata_json")})
        inserted["chunks"] = len(source.get("chunks", []))
        for row in source.get("ingestion_jobs", []):
            workspace_id = row.get("workspace_id") or DEFAULT_WORKSPACE_ID
            _exec(conn, "ingestion_jobs", {"id": row["job_id"], "tenant_id": workspace_tenant.get(workspace_id, DEFAULT_TENANT_ID), "workspace_id": workspace_id, "document_id": row.get("document_id"), "filename": row["filename"], "status": row["status"], "progress": row.get("progress") or 0, "message": row.get("message"), "metadata_json": _json(row, "metadata_json"), "created_at": row["created_at"], "updated_at": row.get("updated_at")})
        inserted["ingestion_jobs"] = len(source.get("ingestion_jobs", []))
        for row in _chat_sessions(source):
            workspace_id = row.get("workspace_id") or DEFAULT_WORKSPACE_ID
            language = row.get("language") or "auto"
            _exec(conn, "chat_sessions", {"id": row["session_id"], "tenant_id": workspace_tenant.get(workspace_id, DEFAULT_TENANT_ID), "workspace_id": workspace_id, "title": row.get("title"), "input_language": language, "response_language": language, "objective_profile": row.get("objective_profile") or "general", "analysis_mode": row.get("analysis_mode") or "quick", "created_at": row["created_at"], "updated_at": row.get("updated_at")})
        inserted["chat_sessions"] = len(_chat_sessions(source))
        for row in source.get("chat_messages", []):
            workspace_id = row.get("workspace_id") or DEFAULT_WORKSPACE_ID
            metadata = _json(row, "metadata_json")
            _exec(conn, "chat_messages", {"id": row["message_id"], "tenant_id": workspace_tenant.get(workspace_id, DEFAULT_TENANT_ID), "workspace_id": workspace_id, "session_id": row["session_id"], "role": row["role"], "content": row["content"], "language": metadata.get("language", "auto"), "metadata_json": metadata, "created_at": row["created_at"]})
        inserted["chat_messages"] = len(source.get("chat_messages", []))
        inserted.update(_copy_simple_context_tables(conn, source, workspace_tenant))
    return inserted


def _copy_simple_context_tables(conn, source: dict[str, list[dict[str, Any]]], workspace_tenant: dict[str, str]) -> dict[str, int]:
    inserted: dict[str, int] = {}
    chunk_ids = {row["chunk_id"] for row in source.get("chunks", [])}
    artifact_ids = {row["artifact_id"] for row in source.get("extracted_artifacts", [])}
    for row in source.get("memory_records", []):
        workspace_id = row.get("workspace_id") or DEFAULT_WORKSPACE_ID
        _exec(conn, "memory_records", {"id": row["memory_id"], "tenant_id": workspace_tenant.get(workspace_id, DEFAULT_TENANT_ID), "workspace_id": workspace_id, "session_id": row["session_id"], "user_id": row.get("user_id") or DEFAULT_USER_ID, "objective_profile": row.get("objective_profile") or "general", "memory_type": row["memory_type"], "content": row["content"], "language": _json(row, "metadata_json").get("language", "auto"), "entities_json": _json(row, "entities_json", []), "metadata_json": _json(row, "metadata_json"), "created_at": row["created_at"], "updated_at": row.get("updated_at")})
    inserted["memory_records"] = len(source.get("memory_records", []))
    for row in source.get("extracted_artifacts", []):
        workspace_id = row.get("workspace_id") or DEFAULT_WORKSPACE_ID
        _exec(conn, "extracted_artifacts", {"id": row["artifact_id"], "tenant_id": workspace_tenant.get(workspace_id, DEFAULT_TENANT_ID), "workspace_id": workspace_id, "document_id": row["document_id"], "artifact_type": row["artifact_type"], "page_number": row["page_number"], "title": row.get("title"), "text": row.get("text") or "", "data_json": _json(row, "data_json"), "bbox_json": _json(row, "bbox_json", None), "created_at": row["created_at"]})
    inserted["extracted_artifacts"] = len(source.get("extracted_artifacts", []))
    for row in source.get("evidence_anchors", []):
        workspace_id = row.get("workspace_id") or DEFAULT_WORKSPACE_ID
        chunk_id = row.get("chunk_id") if row.get("chunk_id") in chunk_ids else None
        artifact_id = row.get("artifact_id") if row.get("artifact_id") in artifact_ids else None
        _exec(conn, "evidence_anchors", {"id": row["anchor_id"], "tenant_id": workspace_tenant.get(workspace_id, DEFAULT_TENANT_ID), "workspace_id": workspace_id, "document_id": row["document_id"], "chunk_id": chunk_id, "artifact_id": artifact_id, "anchor_type": row["anchor_type"], "page_number": row["page_number"], "bbox_json": _json(row, "bbox_json", None), "preview_uri": row.get("preview_path"), "crop_uri": row.get("crop_path"), "citation_text": row.get("citation_text") or "", "metadata_json": _json(row, "metadata_json"), "created_at": row["created_at"]})
    inserted["evidence_anchors"] = len(source.get("evidence_anchors", []))
    for row in source.get("agent_runs", []):
        workspace_id = row.get("workspace_id") or DEFAULT_WORKSPACE_ID
        steps = _json(row, "steps_json", [])
        _exec(conn, "agent_runs", {"id": row["run_id"], "tenant_id": workspace_tenant.get(workspace_id, DEFAULT_TENANT_ID), "workspace_id": workspace_id, "session_id": row.get("session_id"), "objective_profile": row.get("objective_profile") or "general", "analysis_mode": row.get("analysis_mode") or "quick", "status": "completed", "input_json": {}, "output_json": {"steps": steps}, "metadata_json": _json(row, "metadata_json"), "created_at": row["created_at"], "updated_at": None})
        for index, step in enumerate(steps):
            _exec(
                conn,
                "agent_steps",
                {
                    "id": step.get("step_id") or f"{row['run_id']}:{index}",
                    "agent_run_id": row["run_id"],
                    "tenant_id": workspace_tenant.get(workspace_id, DEFAULT_TENANT_ID),
                    "workspace_id": workspace_id,
                    "agent_name": step.get("agent_name") or "unknown",
                    "action": step.get("action") or "migrated_step",
                    "status": step.get("status") or "completed",
                    "input_json": {"summary": step.get("input_summary")},
                    "output_json": {"summary": step.get("output_summary"), "metadata": step.get("metadata", {})},
                    "tool_calls_json": [],
                    "error": None,
                    "started_at": row["created_at"],
                    "completed_at": row["created_at"],
                },
            )
    inserted["agent_runs"] = len(source.get("agent_runs", []))
    inserted["agent_steps"] = sum(len(_json(row, "steps_json", [])) for row in source.get("agent_runs", []))
    for row in source.get("audit_logs", []):
        metadata = _json(row, "metadata_json")
        actor_email = row.get("actor_email")
        if actor_email:
            metadata = {**metadata, "actor_email": actor_email}
        _exec(conn, "audit_logs", {"id": row["audit_id"], "tenant_id": row.get("tenant_id") or DEFAULT_TENANT_ID, "workspace_id": row.get("workspace_id"), "user_id": row.get("user_id") or DEFAULT_USER_ID, "event_type": row["event_type"], "resource_type": row.get("resource_type"), "resource_id": row.get("resource_id"), "status": row.get("status") or "success", "message": row.get("message"), "metadata_json": metadata, "created_at": row["created_at"]})
    inserted["audit_logs"] = len(source.get("audit_logs", []))
    for row in source.get("auth_sessions", []):
        _exec(conn, "auth_sessions", {"id": _stable_id("auth_session", row["session_token_hash"]), "session_token_hash": row["session_token_hash"], "user_id": row["user_id"], "expires_at": row["expires_at"], "revoked_at": row.get("revoked_at"), "created_at": row["created_at"], "updated_at": row.get("revoked_at")})
    inserted["auth_sessions"] = len(source.get("auth_sessions", []))
    for row in source.get("auth_action_tokens", []):
        _exec(conn, "auth_action_tokens", {"token_hash": row["token_hash"], "user_id": row["user_id"], "action": row["action"], "expires_at": row["expires_at"], "used_at": row.get("used_at"), "metadata_json": _json(row, "metadata_json"), "created_at": row["created_at"], "updated_at": row.get("used_at")})
    inserted["auth_action_tokens"] = len(source.get("auth_action_tokens", []))
    for row in source.get("query_logs", []):
        payload = _json(row, "payload_json")
        _exec(conn, "query_logs", {"id": row["query_id"], "tenant_id": payload.get("tenant_id", DEFAULT_TENANT_ID), "workspace_id": payload.get("workspace_id"), "session_id": payload.get("session_id"), "payload_json": payload, "created_at": row["created_at"]})
    inserted["query_logs"] = len(source.get("query_logs", []))
    for row in source.get("evaluation_runs", []):
        payload = _json(row, "payload_json")
        _exec(conn, "evaluation_runs", {"id": row["run_id"], "tenant_id": payload.get("tenant_id", DEFAULT_TENANT_ID), "workspace_id": payload.get("workspace_id"), "status": payload.get("status", "completed"), "dataset_path": payload.get("dataset_path"), "metrics_json": payload.get("metrics", {}), "payload_json": payload, "created_at": row["created_at"]})
    inserted["evaluation_runs"] = len(source.get("evaluation_runs", []))
    return inserted


def _exec(conn, table: str, payload: dict[str, Any]) -> None:
    table_obj = Base.metadata.tables[table]
    payload = _coerce_payload(table_obj, payload)
    conflict = CONFLICT_COLUMNS.get(table, "id")
    insert_factory = postgres_insert if conn.dialect.name == "postgresql" else sqlite_insert
    stmt = insert_factory(table_obj).values(**payload)
    updates = {column: getattr(stmt.excluded, column) for column in payload if column != conflict}
    if updates:
        stmt = stmt.on_conflict_do_update(index_elements=[conflict], set_=updates)
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=[conflict])
    conn.execute(stmt)


def _exec_role(conn, tenant_id: str, role_name: str) -> None:
    now = datetime.utcnow()
    _exec(
        conn,
        "roles",
        {
            "id": f"{tenant_id}:{role_name}",
            "tenant_id": tenant_id,
            "name": role_name,
            "created_at": now,
            "updated_at": now,
        },
    )


def _exec_workspace_member(conn, workspace_id: str, user_id: str, tenant_id: str, role_name: str) -> None:
    table_obj = Base.metadata.tables["workspace_members"]
    role_id = f"{tenant_id}:{role_name}"
    insert_factory = postgres_insert if conn.dialect.name == "postgresql" else sqlite_insert
    stmt = insert_factory(table_obj).values(workspace_id=workspace_id, user_id=user_id, role_id=role_id)
    stmt = stmt.on_conflict_do_update(index_elements=["workspace_id", "user_id"], set_={"role_id": stmt.excluded.role_id})
    conn.execute(stmt)


def _coerce_payload(table_obj, payload: dict[str, Any]) -> dict[str, Any]:
    coerced = dict(payload)
    for column, value in list(coerced.items()):
        if value is None or column not in table_obj.c:
            continue
        if isinstance(table_obj.c[column].type, DateTime) and isinstance(value, str):
            coerced[column] = datetime.fromisoformat(value)
    return coerced


def _build_reference_rows(source: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    now = _migration_timestamp()
    tenants: dict[str, dict[str, Any]] = {
        row["tenant_id"]: {"id": row["tenant_id"], "name": row["name"], "plan": row.get("plan") or "free", "metadata_json": _json(row, "metadata_json"), "created_at": row["created_at"], "updated_at": row.get("updated_at")}
        for row in source.get("tenants", [])
    }
    tenants.setdefault(DEFAULT_TENANT_ID, {"id": DEFAULT_TENANT_ID, "name": "Default Tenant", "plan": "free", "metadata_json": {}, "created_at": now, "updated_at": now})
    for row in source.get("users", []):
        tenant_id = row.get("tenant_id") or DEFAULT_TENANT_ID
        tenants.setdefault(tenant_id, {"id": tenant_id, "name": tenant_id, "plan": "free", "metadata_json": {"created_by": "migration"}, "created_at": now, "updated_at": now})
    for row in source.get("workspaces", []):
        tenant_id = row.get("tenant_id") or DEFAULT_TENANT_ID
        tenants.setdefault(tenant_id, {"id": tenant_id, "name": tenant_id, "plan": "free", "metadata_json": {"created_by": "migration"}, "created_at": now, "updated_at": now})
    return {"tenants": list(tenants.values())}


def _expected_target_counts(source: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    counts = {table: len(source.get(table, [])) for table in MIGRATION_ORDER}
    counts["tenants"] = len(_build_reference_rows(source)["tenants"])
    counts["users"] = len(source.get("users", [])) + len(_synthetic_users(source))
    counts["user_preferences"] = counts["users"]
    counts["agent_steps"] = sum(len(_json(row, "steps_json", [])) for row in source.get("agent_runs", []))
    counts["workspace_members"] = len(_workspace_members(source))
    counts["roles"] = len({(row["tenant_id"], row["role"]) for row in _workspace_members(source)})
    counts["chat_sessions"] = len(_chat_sessions(source))
    return counts


def _target_counts(engine) -> dict[str, int]:
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for table in VALIDATED_TARGET_TABLES + ["agent_steps"]:
            if table in Base.metadata.tables:
                counts[table] = int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
    return counts


def _validate_counts(expected_counts: dict[str, int], target_counts: dict[str, int]) -> dict[str, Any]:
    mismatches = []
    for table, expected in expected_counts.items():
        observed = target_counts.get(table, 0)
        if observed != expected:
            mismatches.append({"table": table, "expected": expected, "observed": observed})
    return {"ok": not mismatches, "mismatches": mismatches}


def _stable_id(namespace: str, value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"aiwana:{namespace}:{value}"))


def _workspace_members(source: dict[str, list[dict[str, Any]]]) -> list[dict[str, str]]:
    workspace_tenant = {row["workspace_id"]: row.get("tenant_id") or DEFAULT_TENANT_ID for row in source.get("workspaces", [])}
    members: dict[tuple[str, str], dict[str, str]] = {}
    for row in source.get("workspaces", []):
        workspace_id = row["workspace_id"]
        user_id = row.get("owner_id") or DEFAULT_USER_ID
        members[(workspace_id, user_id)] = {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "tenant_id": row.get("tenant_id") or DEFAULT_TENANT_ID,
            "role": "owner",
        }
    for row in source.get("workspace_members", []):
        workspace_id = row.get("workspace_id")
        user_id = row.get("user_id")
        role = str(row.get("role") or "viewer").lower()
        if not workspace_id or not user_id:
            continue
        members[(workspace_id, user_id)] = {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "tenant_id": workspace_tenant.get(workspace_id, DEFAULT_TENANT_ID),
            "role": role if role in {"owner", "admin", "analyst", "viewer"} else "viewer",
        }
    return list(members.values())


def _chat_sessions(source: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    sessions = {row["session_id"]: dict(row) for row in source.get("chat_sessions", [])}
    now = _migration_timestamp()
    for table in ("chat_messages", "memory_records"):
        for row in source.get(table, []):
            session_id = row.get("session_id")
            if not session_id or session_id in sessions:
                continue
            sessions[session_id] = {
                "session_id": session_id,
                "workspace_id": row.get("workspace_id") or DEFAULT_WORKSPACE_ID,
                "title": f"Migrated session {session_id}",
                "language": "auto",
                "objective_profile": row.get("objective_profile") or "general",
                "analysis_mode": "quick",
                "created_at": row.get("created_at") or now,
                "updated_at": row.get("updated_at") or row.get("created_at") or now,
            }
    return list(sessions.values())


def _synthetic_users(source: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    existing = {row["user_id"] for row in source.get("users", [])}
    now = _migration_timestamp()
    users = []
    for row in source.get("memory_records", []):
        user_id = row.get("user_id") or DEFAULT_USER_ID
        if user_id in existing:
            continue
        existing.add(user_id)
        users.append(
            {
                "id": user_id,
                "tenant_id": DEFAULT_TENANT_ID,
                "email": f"{user_id}@aiwana.local",
                "display_name": user_id,
                "password_hash": None,
                "password_salt": None,
                "email_verified": False,
                "status": "active",
                "metadata_json": {"created_by": "migration", "synthetic": True},
                "created_at": now,
                "updated_at": now,
            }
        )
    return users


def _migration_timestamp() -> str:
    return "1970-01-01T00:00:00"


def _json(row: dict[str, Any], key: str, default: Any | None = None) -> Any:
    value = row.get(key)
    if value is None:
        return {} if default is None else default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {} if default is None else default


def _redact_url(url: str) -> str:
    if "@" not in url:
        return url
    prefix, suffix = url.rsplit("@", 1)
    scheme = prefix.split("://", 1)[0] if "://" in prefix else "postgresql"
    return f"{scheme}://<redacted>@{suffix}"


if __name__ == "__main__":
    main()
