# Aiwana Production Deploy

1. Copy `.env.production.example` to `.env` and set real secrets for auth, database, Redis, object storage, and LLM providers.
2. Set `APP_ENV=production`, `REQUIRE_AUTH=true`, `ENABLE_LOCAL_USER_FALLBACK=false`, `DATABASE_BACKEND=postgres`, and all Redis backends to `redis`.
3. Start dependencies and services with `docker compose -f docker-compose.prod.yml up --build`. The API container runs `alembic upgrade head` before Uvicorn starts.
4. Run `python tools/generate_ingestion_validation_corpus.py` locally or in CI when validating large-document/OCR ingestion.
5. Run graph lift eval with `POST /evaluation/graph-lift` or a small script before production launch; `/readiness/launch` blocks production when graph memory is enabled and no passing graph-lift run exists.
6. Open `/readiness/launch`; production launch is blocked until every blocker is resolved.
7. Run strict smoke tests with `AIWANA_SMOKE_STRICT=true` and either `AIWANA_SMOKE_TOKEN` or `AIWANA_SMOKE_EMAIL`/`AIWANA_SMOKE_PASSWORD`: `python tools/smoke_prod.py`.
8. Run seeded RAG evals and backup/restore drill before external users.

## Local Production Validation

On Windows, run `powershell -ExecutionPolicy Bypass -File tools/run_local_prod.ps1`. The script deduplicates `Path`, installs backend requirements unless `-SkipInstall` is passed, starts Postgres/Redis/Qdrant with Docker Compose, runs Alembic migrations, then starts the backend, worker, and frontend.

For first-time smoke auth, use a disposable smoke account:

```powershell
$env:AIWANA_SMOKE_STRICT="true"
$env:AIWANA_SMOKE_BOOTSTRAP="true"
$env:AIWANA_SMOKE_EMAIL="smoke@aiwana.local"
$env:AIWANA_SMOKE_PASSWORD="aiwana-smoke-password"
python tools\smoke_prod.py
```

If `psycopg` is missing, install `requirements-backend.txt` in the active Python environment. If ports `8000` or `3000` are busy, stop the existing process or pass `-BackendPort` / `-FrontendPort` to the runner.

## Hugging Face Setup

HF execution is optional and task-scoped. Install heavy dependencies only where needed:

```powershell
python -m pip install -r requirements-hf.txt
python tools\hf_healthcheck.py
```

Enable only tasks that pass local health and latency checks. Keep captioning/OCR/VLM disabled until their model load time and memory usage are acceptable for your deployment target.

Rollback: keep the previous image tag and database backup marker. If readiness fails after deploy, restore the previous image and run `ops/restore-drill.md`.

## Required Services

- API: FastAPI backend on port 8000.
- Frontend: Next.js app on port 3000.
- Worker: `python -m tools.worker` for queued ingestion/OCR/embedding/artifact work.
- Postgres: primary metadata database.
- Redis: rate limits, session/cache, queue, worker heartbeat.
- Qdrant: vector search.
- MinIO/S3: production artifact storage.
- Neo4j: optional profile for future external graph backend; current graph abstraction still works through Postgres.

## Captive Data and AWS boundary

The application keeps tenant/workspace/document references on every supported
metadata record. In shared mode, Postgres/RLS, Redis namespacing, Qdrant payload
filters, and private S3 prefixes provide logical isolation. `TENANT_DATA_PLANE_MODE`
and `TenantDataPlaneResolver` also define a dedicated mode using secret
references; actual per-tenant RDS/Redis/Qdrant provisioning is infrastructure
work that must be completed before claiming physical isolation.

Recommended AWS topology:

```text
CloudFront/WAF -> private ALB -> API + worker/OCR (private subnets)
                              -> RDS PostgreSQL
                              -> ElastiCache Redis
                              -> private Qdrant
                              -> private S3 (SSE-KMS)
                              -> Bedrock or private vLLM endpoint
```

Use `ObjectStore` for S3-backed originals/previews with keys of the form
`tenants/{tenant_id}/workspaces/{workspace_id}/documents/{document_id}/...`.
S3 lifecycle rules are only a safety net: application purge must still remove
Postgres, Qdrant, Redis, graph, and derived records. Backup retention is shown
separately from application retention; a verified production purge cannot claim
that encrypted backup copies vanished before their documented expiry.

Security-group intent:

- Internet to ALB: 443 only.
- ALB to API: application port only.
- API/worker to RDS, Redis, and Qdrant: private security-group rules.
- Internet to RDS, Redis, and Qdrant: blocked.
- AWS credentials and KMS/S3 secrets: Secrets Manager or task-role references,
  never frontend configuration or normal metadata fields.

## Captive Data validation

The local 200-page fixture can be measured without a live provider using:

```powershell
python tools\benchmark_long_documents.py
```

Run live Fast/Balanced/Deep/Auto query timing with:

```powershell
python tools\benchmark_query_modes.py --token $env:AIWANA_SMOKE_TOKEN
```

Both commands write raw JSON under `data/benchmarks`; they do not infer OCR,
embedding, Qdrant, graph, or LLM timings when those services are unavailable.

## Known Limitations

- Native streaming now emits provider tokens during generation for `/chat/query/stream`, but the synchronous `/query` endpoint remains the compatibility path.
- Retrieval cache is Redis-backed and invalidated on ingestion completion and document delete; monitor cache hit rate in observability.
- Streaming cancellation is recorded when the client disconnects, but provider-level hard cancellation depends on the provider SDK.
- Worker queue foundation is active, but full distributed OCR/embedding fanout still needs load testing.
- Hugging Face task providers lazy-load and degrade to deterministic fallbacks when local models or dependencies are unavailable.
- `tools/hf_healthcheck.py` reports cold/warm task behavior; do not enable slow HF tasks on the request path.
- OIDC/SAML are still future enterprise hardening items.
