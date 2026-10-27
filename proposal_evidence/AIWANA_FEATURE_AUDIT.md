# Aiwana Feature Audit

**As of:** 2026-09-08  
**Scope:** repository inspection, automated tests, frontend production build, local backend startup, long-document benchmark, and authenticated UI capture.  
**Purpose:** factual product and proposal evidence. This document does not convert a code path into a production claim.

## Evidence rules

- **Working + tested** means the behavior is implemented and covered by the repository's automated tests. It does not mean a sustained production deployment has been observed.
- **Implemented, needs live infrastructure validation** means the code path and tests exist, but the current session did not prove it against the corresponding production service.
- **Enterprise deployment option / foundation** means the architecture or adapter exists and can support a deployment choice, but provisioning, operations, and acceptance evidence are incomplete.
- **Roadmap / not implemented** means it must not appear as a current capability in client-facing material.

## Current capability matrix

| Capability | Evidence inspected | Status | Safe proposal wording |
|---|---|---|---|
| Next.js product shell and route screens | `frontend/app/*`, `frontend/components/*`, successful `npm run build` | Working + tested | A working web application with dashboard, chat, sources, evidence, Data Vault, admin and settings surfaces |
| Dark/light theme and responsive layout | `frontend/components/AppShell.tsx`, styles, production build | Working + tested | Responsive web UI with dark/light modes |
| Auth and session handling | `app/api/routes/auth.py`, `app/api/auth_context.py`, auth tests | Working + tested | Authentication is required by production defaults and protected routes enforce workspace context |
| RBAC and tenant scoping | `app/api/rbac.py`, workspace/document/query routes, tenant tests | Working + tested | Role and workspace checks are implemented and test-covered |
| PDF, DOCX, PPTX, XLSX and CSV ingestion paths | `app/services/ingestion/parser.py`, parser tests | Working + tested | Multi-format ingestion is implemented; file-specific production corpus validation remains required |
| Chunking and metadata preservation | `chunker.py`, parser/indexer tests | Working + tested | Chunk metadata supports page, section, table, sheet, slide and source context where parser output provides it |
| Dense, sparse and hybrid retrieval | `app/services/retrieval/*`, Qdrant storage, retrieval tests | Working + tested | Hybrid retrieval is implemented with tenant-aware filters |
| Reranking and query modes | `app/services/retrieval/reranker.py`, `query_modes.py`, query-mode tests | Working + tested | Fast, balanced and deep retrieval policies are available with bounded reranking |
| Agentic query trace | `app/services/agentic/*`, `app/api/routes/query.py`, ownership/stream tests | Working + tested | The product exposes audit-safe plans, tools, evidence and verification metadata |
| Grounding, citations and abstention | citation verifier, verification schemas and tests | Working + tested | Answers can be blocked or marked low-confidence when evidence is insufficient |
| Native streaming foundation | `app/services/streaming/sse.py`, provider hooks and stream tests | Implemented, needs live infrastructure validation | Provider-native streaming is implemented and test-covered; live provider latency and cancellation need deployment proof |
| Graph memory abstraction and extraction | `app/services/graph_memory.py`, graph proof tests | Implemented, needs live infrastructure validation | Graph extraction/retrieval is available through a Postgres graph abstraction; live graph-lift evidence is pending |
| OCR and multimodal artifact metadata | `app/services/ingestion/multimodal.py`, artifact extractor, parser/OCR tests | Implemented, needs live infrastructure validation | OCR and multimodal extraction paths exist with explicit metadata and failure handling |
| 200-page text/multimodal parsing | `data/validation_latency/aiwana_200_page_multimodal_benchmark.pdf`, benchmark output | Working + tested for parse/chunk path | A 200-page synthetic benchmark parsed to 270 chunks; this is not proof of scanned OCR/query SLA |
| 200-page scanned PDF reliability | No live scanned corpus run in this session | Roadmap / not implemented as a proven guarantee | Validate in a pilot corpus before promising scanned-document performance |
| Postgres metadata backend and migrations | `app/db/models.py`, `postgres_metadata.py`, Alembic revisions | Implemented, needs live infrastructure validation | Postgres is the intended production metadata backend |
| Redis cache, queue and rate-limit integrations | `redis_client.py`, `query_cache.py`, worker queue and tests | Implemented, needs live infrastructure validation | Redis-backed cache/queue foundations exist; live failover and sustained worker proof remain |
| Qdrant vector store | `app/storage/qdrant.py`, local startup and tenant filter tests | Implemented, needs live infrastructure validation | Qdrant is the intended vector store with tenant-aware payload filters |
| Worker foundation | `app/services/worker/queue.py`, `runner.py`, worker tests | Implemented, needs live infrastructure validation | Background processing foundations exist; distributed worker operations are not yet proven |
| Data Vault overview and document footprint | `app/services/data_vault.py`, `app/api/routes/data_vault.py`, tests | Working + tested | Users can inspect document-level data footprint and processing summaries |
| Data lineage | `DataLineage` schemas/service and lineage route | Working + tested | A document lineage view tracks lifecycle stages where metadata exists |
| Purge requests, approval and receipts | deletion request schema/repositories, purge service, tests | Working + tested in local metadata fixtures | Verified purge workflow and receipts exist; backup-retention caveats remain explicit |
| Retention policy engine | `app/services/retention.py`, cleanup tool and tests | Working + tested | Retention policy evaluation and cleanup tooling are implemented |
| Object storage abstraction | `app/storage/object_store.py` | Enterprise deployment option / foundation | Local and S3-compatible object-store abstractions support tenant-safe keys and encryption configuration |
| Dedicated tenant data plane resolver | `app/services/tenant_data_plane.py`, deployment docs | Enterprise deployment option / foundation | Dedicated data-plane deployment is an architecture option, not a provisioned environment |
| API keys and invitations | auth routes/services and tests | Working + tested | Workspace-scoped API key and invitation foundations exist |
| Browser extension capture scaffold | `browser-extension/*`, browser route/tests | Implemented, needs live infrastructure validation | A browser capture path exists; extension distribution and full authenticated UX need hardening |
| Industry pack catalog | `app/api/routes/industry_packs.py`, frontend and tests | Working + tested | Industry-oriented starter packs/catalog are available; vertical accuracy needs customer data |
| Observability and readiness | `app/services/observability/*`, readiness services, admin UI | Implemented, needs live infrastructure validation | Health, readiness, cache, worker, provider and graph signals are surfaced when dependencies are live |
| Backup and restore tooling | `tools/backup.py`, `tools/restore.py`, backup tests, ops docs | Implemented, needs live infrastructure validation | Backup/restore tooling and runbook exist; a production restore drill is still required |
| Private-only LLM policy | `app/core/config.py`, indexer/runtime enforcement, privacy tests | Working + tested as policy control | Private-only mode can reject external processing when configured |
| Full native Zimyo integration | No verified connector/API contract in repository | Roadmap / not implemented | Position as an integration pilot, not a shipped native connector |
| Physical per-customer isolated deployment | Resolver and deployment docs only | Enterprise deployment option / foundation | Dedicated deployment can be designed and provisioned as a paid enterprise option |
| SSO/SAML and compliance certification | No complete verified implementation/evidence | Roadmap / not implemented | Do not claim SSO/SAML, SOC 2, HIPAA, GDPR certification, or external compliance |

## Captive Data lifecycle

| Layer | Current storage/control evidence | Tenant visibility | Deletion reality |
|---|---|---|---|
| Original upload | Local upload/object-store abstraction; S3-compatible adapter exists | Workspace/document scoped in application paths | Purge service manages known local/object references; production object-store wiring needs validation |
| Extracted text and chunks | Metadata repository plus indexed chunk payloads | Tenant/workspace filters are enforced in tested paths | Chunk records and vector points have deletion paths; full production sweep needs drill |
| OCR and page artifacts | Page metadata, preview/artifact references, multimodal extraction services | Exposed through document status/footprint where populated | Page-level purge is implemented as a control; live scanned corpus proof is pending |
| Embeddings and vector index | Qdrant adapter; local file fallback used for demo startup | Payload filters include tenant/workspace constraints | Document/vector deletion is implemented; Qdrant server verification was not live in this audit |
| Graph facts | Postgres graph abstraction with provenance/source links | Workspace-scoped graph retrieval/tests | Document graph deletion preserves shared entities where appropriate; live graph store proof pending |
| Query context and citations | Agent runs/query logs and response metadata | Workspace query authorization | Context is query-time; stored log detail varies by configuration, so export is metadata-focused |
| Redis cache/session/job state | Redis client/cache/queue abstractions | Keys are designed to be workspace/tenant namespaced | TTL/invalidation paths exist; live Redis behavior was not observed in this session |
| Retention and deletion | Retention policy engine, deletion requests, purge receipts | Workspace/admin controls | Verification is explicit, with a backup-retention caveat; do not say deletion from every backup is proven |

## What the screenshots prove

The 16 screenshots prove that the authenticated product shell and Data Vault/admin surfaces render. The captured demo workspace had zero indexed documents because signup selected a newly-created workspace while the UI remained on `Default workspace`. Therefore the screenshots do **not** prove successful document indexing, populated citations, graph evidence, purge execution, or a live production dependency health state. See `SCREENSHOT_MANIFEST.md`.

## Launch assessment

Aiwana is credible as an enterprise-pilot candidate with a differentiated Captive Data control plane. It is not yet supportable as a blanket “production-ready for every industry” product without a live Postgres/Redis/Qdrant/worker smoke run, scanned-document corpus validation, backup restore drill, sustained load test, customer-specific security review, and a verified Zimyo integration contract.
