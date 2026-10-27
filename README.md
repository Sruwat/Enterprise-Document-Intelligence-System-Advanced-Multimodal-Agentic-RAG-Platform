# Aiwana Enterprise Document Intelligence Platform

Aiwana is a private, citation-safe document intelligence workspace built with FastAPI, Next.js, PostgreSQL/SQLite metadata adapters, Redis, Qdrant and local/provider-abstracted AI services. It turns long and multimodal business documents into searchable evidence, grounded answers and an inspectable data lifecycle.

**Product thesis:** Your documents. Your vectors. Your retention. Your control.

Aiwana is currently an enterprise-pilot candidate. The repository has broad automated coverage and a working local UI, but a production launch still requires live Postgres/Redis/Qdrant/worker smoke validation, representative OCR and load testing, backup/restore drills, deployment hardening and a customer-specific security review.

## What this project actually is

Aiwana combines two products in one workspace:

1. **Agentic document intelligence:** ingest documents, parse pages/tables/slides, retrieve relevant evidence using dense/sparse/hybrid search, rerank candidates, use graph context when enabled, stream answers and expose citations, confidence and grounding status.
2. **Captive Data control plane:** inspect document footprint and lineage across originals, extracted content, chunks, vectors, graph facts and query evidence; apply processing/retention policies; submit purge requests; and record verification receipts.

It is not a generic chatbot and it does not claim zero leakage, universal scanned-PDF reliability, compliance certification, a native Zimyo connector or a live dedicated cloud environment by default.

## Implemented capabilities

- SaaS-style auth, persistent knowledge spaces, private-mode workspaces and workspace-scoped chat sessions
- Source ingestion jobs with progress for PDFs, DOCX contracts, images and pasted text
- Page-aware retrieval with hybrid search, multilingual reranking, citations and abstention
- Evidence Canvas with citations, page previews, artifact cards, confidence and agent steps
- Objective profiles for Legal/Contracts, Research/Study and Enterprise Docs
- Persistent short-term chat context plus long-term memory summaries
- Agent pipeline for context building, retrieval planning, evidence selection, objective analysis and synthesis
- Next.js app shell with dashboard, chat, sources, evidence, Data Vault, admin, settings, features and use-case pages
- Production-default authentication, workspace ownership checks, RBAC, API keys and invitation foundations
- Agentic query planning, tool traces, retrieval metadata, grounding verification, abstention and native-streaming foundation
- Dense, sparse and hybrid retrieval, query modes, reranking, citations, graph extraction/retrieval abstraction and evidence canvas
- Data Vault footprint, lineage, retention policy, deletion requests, purge verification and receipts
- Redis cache/queue foundations, worker runner, Hugging Face task registry, browser capture scaffold and observability/readiness APIs

## Evidence and current limits

The repository contains a factual audit and proposal evidence pack under [`proposal_evidence/`](proposal_evidence/):

- [`AIWANA_FEATURE_AUDIT.md`](proposal_evidence/AIWANA_FEATURE_AUDIT.md) — feature-by-feature status and Captive Data lifecycle
- [`TECHNICAL_PROOF.md`](proposal_evidence/TECHNICAL_PROOF.md) — exact test/build/benchmark evidence and limits
- [`SCREENSHOT_MANIFEST.md`](proposal_evidence/SCREENSHOT_MANIFEST.md) — captured UI surfaces and capture caveats
- [`AIWANA_X_ZIMYO_PROPOSAL.md`](proposal_evidence/AIWANA_X_ZIMYO_PROPOSAL.md) — claim-safe commercial proposal source pack

Latest verified local evidence includes:

- Backend: `167 passed, 6 warnings` with the repository virtual environment
- Frontend: production build passes; desktop/mobile Playwright coverage passes (`9 passed, 1 skipped`)
- Long document parser benchmark: 200 synthetic pages, 270 chunks; OCR and live vector timings were not included

Still required before a broad production launch: live Postgres/Redis/Qdrant/worker smoke, scanned-document corpus validation, sustained concurrency benchmarks, backup/restore drill, SSO/SAML if required, cloud deployment proof and an external/customer security review.

## Optional quality upgrades

PDF page previews and image metadata ship in the normal runtime. For local OCR over scanned documents and images, additionally install:

```bash
pip install -r requirements-backend.txt -r requirements-multimodal.txt
```

- `PyMuPDF` renders PDF page previews used by evidence cards in the standard install.
- `PaddleOCR` is loaded locally only when its optional dependencies are installed and `ENABLE_MULTIMODAL=true`; scanned pages and images then gain searchable OCR text.
- For launch retrieval, download `BAAI/bge-m3`, point `EMBEDDING_MODEL_PATH` at it, set `QDRANT_COLLECTION=aiwana_chunks_v2`, and re-ingest sources. The old `rag_chunks` collection should remain untouched until v2 ingestion is verified.

Hosted vision-language descriptions and page-image multivector search are extension points for a later deployment profile; they are not silently invoked by the local runtime.

## V2 Migration

1. Download local launch models:

```bash
python tools/download_aiwana_models.py
```

2. Update `.env` to the launch profile:

```env
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_MODEL_PATH=./models/bge-m3
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RERANKER_MODEL_PATH=./models/bge-reranker-v2-m3
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=aiwana_chunks_v2
ENABLE_NAMED_VECTORS=true
ENABLE_BGE_M3_SPARSE=false
ENABLE_PERSISTENT_MEMORY=true
```

You can apply only those non-secret keys automatically:

```bash
python tools/configure_launch_profile.py --apply
```

3. Dry-run the migration:

```bash
python tools/launch_doctor.py
python tools/migrate_aiwana_v2.py --dry-run
```

4. Re-index existing source files into the v2 collection:

```bash
python tools/migrate_aiwana_v2.py --reingest
```

The migration script refuses `--reingest` unless the active profile is BGE-M3 plus the v2 collection, which prevents accidentally rebuilding launch vectors into the legacy `rag_chunks` collection.
For SaaS launch, run re-ingestion against a Qdrant server. File fallback re-ingestion is blocked unless you pass `--allow-local-fallback` for a local-only test.

## Launch Gate Commands

Start Qdrant and verify the v2 collection:

```bash
docker compose up -d qdrant
python tools/verify_qdrant_v2.py
python tools/migrate_aiwana_v2.py --dry-run
```

Create and validate a deterministic backup bundle before launch:

```bash
python tools/backup_restore.py backup --output data/backups/launch-smoke
python tools/backup_restore.py restore --input data/backups/launch-smoke --dry-run
```

Run final checks:

```bash
pytest tests
cd frontend && npm run build && npm run test:e2e
cd ..
python tools/launch_doctor.py
```

Production must set `REQUIRE_AUTH=true`, use a non-console email provider, keep rate limiting and security headers enabled, and use Qdrant server storage instead of local file fallback.

## Architecture at a glance

```text
Next.js workspace / browser extension
              |
          FastAPI API
              |
  Auth + RBAC + workspace isolation
              |
   Agentic query engine and workers
      |          |          |
  Postgres     Redis      Qdrant
 metadata/    cache/jobs  vectors
 graph/logs
      |
 parser -> OCR/multimodal -> chunks -> embeddings -> retrieval -> rerank
                                      -> citations -> verification -> answer
```

Postgres is the intended production metadata and graph backend, Redis is the intended volatile/cache/queue backend, and Qdrant is the intended vector backend. SQLite and local file-backed Qdrant remain useful for development and offline tests.

## API surface

```text
POST /workspaces
GET  /workspaces
POST /workspaces/{workspace_id}/sources
POST /workspaces/{workspace_id}/sources/text
GET  /ingestions/{job_id}
POST /chat/sessions
POST /chat/query
POST /chat/query/stream
GET  /documents?workspace_id={workspace_id}
GET  /documents/{document_id}/artifacts
GET  /workspaces/{workspace_id}/documents/{document_id}/pages/{page_number}/preview
GET  /audit/logs
POST /evaluation/run
GET  /evaluation/launch-gates
GET  /readiness/launch
DELETE /workspaces/{workspace_id}/documents/{document_id}
```

The legacy `POST /ingest/pdf` and `POST /query` endpoints remain available for existing integrations.

Additional routes cover health/readiness, observability, Data Vault, graph evaluation, browser capture, API keys, invitations and admin operations. See the route modules under [`app/api/routes/`](app/api/routes/).

## Docker quick start

1. Copy `.env.example` to `.env` and optionally provide `GROQ_API_KEY`.
2. Run:

```bash
docker compose up --build
```

3. Open:

- Next.js workspace: `http://localhost:3000`
- FastAPI health: `http://localhost:8000/health`
- Qdrant dashboard: `http://localhost:6333/dashboard`

Without a configured hosted LLM key, answers use the local evidence-extractive fallback. In a private-mode workspace, Aiwana always uses local answer generation.

## Local Development

```bash
pip install -r requirements.txt
uvicorn app.api.main:app --reload
pytest -q
```

For frontend development:

```bash
cd frontend
npm install
npm run dev
```
