from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request


def request_json(name: str, method: str, url: str, token: str | None = None, payload: dict | None = None, timeout: int = 15) -> tuple[bool, dict]:
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            body = json.loads(raw) if raw.strip() else {}
            ok = 200 <= response.status < 400
    except Exception as exc:
        print(f"[FAIL] {name}: {exc}")
        return False, {"error": str(exc)}
    print(f"[{'OK' if ok else 'FAIL'}] {name}: {method} {url}")
    return ok, body if isinstance(body, dict) else {"body": body}


def check_url(name: str, url: str, token: str | None = None) -> bool:
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            ok = 200 <= response.status < 400
    except Exception as exc:
        print(f"[FAIL] {name}: {exc}")
        return False
    print(f"[{'OK' if ok else 'FAIL'}] {name}: {url}")
    return ok


def login(api: str) -> str | None:
    token = os.getenv("AIWANA_SMOKE_TOKEN")
    if token:
        return token
    email = os.getenv("AIWANA_SMOKE_EMAIL")
    password = os.getenv("AIWANA_SMOKE_PASSWORD")
    if not email or not password:
        return None
    ok, body = request_json("auth login", "POST", f"{api}/auth/login", payload={"email": email, "password": password})
    if ok:
        return body.get("session_token")
    if os.getenv("AIWANA_SMOKE_BOOTSTRAP", "false").lower() not in {"1", "true", "yes", "on"}:
        return None
    ok, body = request_json(
        "auth signup bootstrap",
        "POST",
        f"{api}/auth/signup",
        payload={"email": email, "password": password, "display_name": "Aiwana Smoke User"},
    )
    return body.get("session_token") if ok else None


def main() -> int:
    api = os.getenv("AIWANA_API_BASE", "http://localhost:8000").rstrip("/")
    frontend = os.getenv("AIWANA_FRONTEND_BASE", "http://localhost:3000").rstrip("/")
    workspace_id = os.getenv("AIWANA_SMOKE_WORKSPACE", "default")
    strict = os.getenv("AIWANA_SMOKE_STRICT", "false").lower() in {"1", "true", "yes", "on"}
    token = login(api)
    checks: list[bool] = []

    if strict and not token:
        print("[FAIL] strict smoke requires AIWANA_SMOKE_TOKEN or AIWANA_SMOKE_EMAIL/AIWANA_SMOKE_PASSWORD.")
        return 1

    checks.append(check_url("frontend", frontend))
    ok, health = request_json("backend health", "GET", f"{api}/health")
    checks.append(ok)
    checks.append((health.get("postgres_runtime") or {}).get("status") in {"ok", None})
    ok, readiness = request_json("launch readiness", "GET", f"{api}/readiness/launch", token)
    checks.append(ok and readiness.get("status") in {"ready", "warning"} if not strict else ok and readiness.get("status") == "ready")
    checks.append(request_json("worker health", "GET", f"{api}/worker/health", token)[0] if token else not strict)
    checks.append(request_json("observability", "GET", f"{api}/observability/workspaces/{workspace_id}/snapshot", token)[0] if token else not strict)

    if token:
        checks.append(
            request_json(
                "query",
                "POST",
                f"{api}/query",
                token,
                {
                    "workspace_id": workspace_id,
                    "question": "Smoke test: what sources are available?",
                    "top_k": 1,
                    "return_evidence_canvas": False,
                },
                timeout=45,
            )[0]
        )
        checks.append(
            request_json(
                "text ingestion",
                "POST",
                f"{api}/workspaces/{workspace_id}/sources/text",
                token,
                {
                    "title": f"smoke-source-{int(time.time())}",
                    "text": "Aiwana production smoke source. This validates authenticated ingestion and queue readiness.",
                    "metadata": {"source_type": "smoke"},
                },
            )[0]
        )
        capture_payload = {
            "workspace_id": workspace_id,
            "title": "Aiwana Smoke Browser Capture",
            "url": "https://example.com/aiwana-smoke",
            "text": "Aiwana browser extension smoke capture text.",
        }
        checks.append(request_json("browser capture", "POST", f"{api}/browser/capture", token, capture_payload)[0])
        checks.append(
            request_json(
                "browser current-page query",
                "POST",
                f"{api}/browser/current-page/query",
                token,
                {**capture_payload, "question": "What does this page mention?"},
            )[0]
        )
    else:
        print("[INFO] Auth token not set; protected checks skipped because strict mode is off.")

    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
