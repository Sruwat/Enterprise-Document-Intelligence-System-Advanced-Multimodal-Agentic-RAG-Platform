# Aiwana × Zimyo
## Captive Data as the control plane for private HR knowledge

**Proposal source pack**  
**Prepared:** 2026-09-08  
**Evidence basis:** repository audit, automated tests, local runtime validation, frontend build, long-document benchmark, authenticated UI capture, and public Zimyo product material.

<!-- PAGE 01 -->
## 1. Executive proposition

Zimyo already brings together the workflows where employees and HR teams need dependable answers: employee information, policies, documents, attendance, payroll, learning and helpdesk. Aiwana can sit beside those workflows as a private document-intelligence layer, turning governed enterprise knowledge into cited, inspectable answers.

The commercial idea is simple: **Your documents. Your vectors. Your retention. Your control.**

Aiwana's differentiator is not merely a chat box. It is the control plane around document intelligence: what entered the system, what was extracted, what was embedded, what was retrieved, what evidence supported the answer, what was retained, and what was requested for deletion.

<!-- PAGE 02 -->
## 2. Why this matters for Zimyo

HR platforms accumulate policy documents, payroll explanations, attendance rules, onboarding material, help articles, compliance guidance and customer-specific operating procedures. Users often need a fast answer, but the organization needs the answer to be grounded in the right policy and traceable to the source.

Aiwana is positioned for questions such as:

- “Which leave rule applies to this employee group and where is the source policy?”
- “What does the payroll guide say about arrears and approval?”
- “Which attendance exception process applies to a remote employee?”
- “What onboarding documents are required for this entity?”

These are pilot questions, not a claim that Aiwana has already been integrated with Zimyo's production APIs.

<!-- PAGE 03 -->
## 3. Public Zimyo context

Zimyo's official product material describes HR, payroll, attendance and leave, employee self-service, learning, helpdesk, documents and policy-related workflows. Its HR software page also describes employee data, onboarding/offboarding, document and policy management, payroll, attendance, learning and helpdesk capabilities. [Official Zimyo HR software page](https://www.zimyo.com/hr-software/)

This creates a natural intelligence adjacency: answer questions over the governing documents that explain those workflows, while respecting customer-specific data boundaries.

The proposal should validate the exact integration points, APIs, event model, tenancy model, identity provider and deployment requirements during discovery.

<!-- PAGE 04 -->
## 4. The Captive Data thesis

Many enterprise RAG demos show the answer and hide the lifecycle. Captive Data makes the lifecycle a first-class product surface.

**Capture:** original document and source metadata.  
**Interpret:** parser output, OCR, pages, tables, images and artifacts.  
**Represent:** chunks, embeddings, vector points and graph facts.  
**Use:** retrieval, context, citations, agent trace and answer verification.  
**Govern:** retention policy, access, deletion request, purge verification and receipt.

Current code implements and tests substantial parts of this lifecycle. The production proposal must distinguish tested controls from live infrastructure proof.

<!-- PAGE 05 -->
## 5. Before and after

```text
BEFORE: document -> opaque ingestion -> vector index -> chat answer
        visibility: limited
        deletion: uncertain across derived layers
        evidence: inconsistent

AFTER WITH CAPTIVE DATA:
document -> parse/OCR -> pages/artifacts -> chunks -> embeddings
         -> Qdrant/vector evidence + Postgres graph facts
         -> retrieval trace -> cited/verified answer
         -> retention -> approved purge -> verification receipt
```

The “after” is the Aiwana product direction. The repository proves the application controls and test paths; a customer pilot proves them against the customer's selected deployment and documents.

<!-- PAGE 06 -->
## 6. Product experience

The web application includes a dashboard, Chat, Sources, Evidence, Data Vault, Admin and Settings surfaces. The captured UI shows an authenticated shell, workspace navigation, theme control, health/readiness surfaces, industry packs and Captive Data controls.

Asset: `proposal_evidence/screens/01_dashboard.png`  
Status: working UI capture; empty demo tenant, not a production health proof.

<!-- PAGE 07 -->
## 7. Ingestion and source intelligence

Aiwana has parser and ingestion paths for PDF, DOCX, PPTX, XLSX and CSV. Page, section, table, sheet and slide metadata can be carried into chunks where the parser produces it. Multimodal and OCR services expose explicit metadata and failure paths.

Assets: `02_document_upload.png`, `15_industry_packs.png`  
Status: working/tested foundation. Live customer corpus, scanned-PDF quality and queue throughput are pilot gates.

<!-- PAGE 08 -->
## 8. Agentic answers

The query layer includes planning, retrieval strategy, tools, evidence inspection, verification, citations, confidence and grounding status. The user-visible contract is audit-safe: plan intent, tools used, evidence inspected, verification and citations, not private chain-of-thought.

Assets: `03_chat_with_citations.png`, `16_query_modes.png`  
Status: implemented/tested contract; the captured workspace had no indexed document, so it does not prove a populated answer.

<!-- PAGE 09 -->
## 9. Evidence and graph intelligence

Dense, sparse and hybrid retrieval, reranking, graph extraction and citation verification are present in the codebase. Graph facts carry source/provenance concepts and can participate in the evidence path. A live graph-lift score still needs to be run on seeded and customer-relevant cases.

Asset: `04_evidence_view.png`, `08_vector_index_chunks.png`  
Safe claim: “Graph-enhanced evidence is an available capability to validate.”  
Unsafe claim: “Graph improves every answer.”

<!-- PAGE 10 -->
## 10. Data Vault

The Data Vault is the strongest product differentiator for this proposal. It provides a document footprint view, lifecycle lineage, privacy/processing boundary signals, retention controls and deletion workflows. It turns vector and derived-data concerns into an inspectable operating model.

Assets: `05_data_vault_overview.png`, `06_document_data_footprint.png`, `07_data_lineage.png`  
Status: tested application controls, shown in an empty/degraded local tenant.

<!-- PAGE 11 -->
## 11. Retention and privacy controls

Retention policy evaluation, temporary-document cleanup tooling, metadata export, object-store abstraction, purge requests and verification receipts are present. The implementation explicitly preserves a backup-retention caveat; no proposal should say that every backup copy is immediately deleted.

Assets: `09_privacy_processing_boundary.png`, `10_retention_policy.png`  
Recommended customer discussion: retention classes, legal hold, derived-data policy, backup window, encryption keys, operator access and restore procedure.

<!-- PAGE 12 -->
## 12. Delete everywhere, honestly

The application supports deletion requests, approval, idempotent purge behavior, verification and receipts across known metadata/vector/graph/object references. That is materially stronger than a UI-only delete button.

Assets: `11_delete_everywhere.png`, `12_deletion_verification.png`, `13_deletion_receipt.png`  
Boundary: production deployment must connect every storage layer, run a restore drill and document backup retention before offering a deletion SLA.

<!-- PAGE 13 -->
## 13. Governance and operating model

Authentication defaults to required in production. RBAC, workspace ownership checks, tenant filters, API keys and invitation foundations are present. Admin surfaces expose readiness, workers, providers, cache and graph status when the corresponding services are available.

Asset: `14_admin_rbac.png`  
Status: test-backed foundation; current local capture reports unknown health because it was not the full Postgres/Redis/Qdrant stack.

<!-- PAGE 14 -->
## 14. Deployment choices

### Shared logical isolation

One managed application with tenant/workspace-scoped authorization, metadata, vector filters and namespaced cache. This is the fastest pilot path and is the current application model.

### Dedicated customer data plane

A separate deployment boundary can place customer metadata, object storage, vectors, queues and keys in a customer-specific environment. The repository includes a resolver and deployment architecture foundation, but no per-customer cloud environment has been provisioned in this audit.

The selection should be made with Zimyo and the customer after data classification and security review.

<!-- PAGE 15 -->
## 15. Zimyo use-case pilots

1. **HR policy copilot:** cited answers over leave, attendance, onboarding and employee policy documents.
2. **Payroll knowledge assistant:** explain payroll guides, statutory process documents and approval rules with source references.
3. **Helpdesk knowledge:** ground answers in approved help articles, SOPs and escalation policies.
4. **Onboarding intelligence:** find required documents, owners, steps and exceptions.
5. **LMS and policy discovery:** answer questions over training material and policy updates.
6. **Admin evidence workspace:** inspect why an answer was produced and which source page supported it.

Each use case should begin with a bounded document set and a measured question set.

<!-- PAGE 16 -->
## 16. Engineering validation

The current evidence pack contains:

- `167 passed, 6 warnings` in the full backend test suite using the repository virtual environment.
- `8 passed` in focused Captive Data/query mode tests.
- successful Python compile check.
- successful Next production build.
- 200-page synthetic parse/chunk benchmark: 270 chunks, parse `33429.64 ms`, chunk `23.33 ms`, OCR disabled.
- historical query telemetry showing reranking and long-tail latency are still optimization areas.

The next acceptance gate is an authenticated strict smoke run with live Postgres, Redis, Qdrant, worker and object storage, plus scanned and long-document validation.

<!-- PAGE 17 -->
## 17. Pilot plan

### Stage 1: Discovery and boundary design

Select document classes, identity model, tenancy boundary, retention classes, integration points and evaluation questions.

### Stage 2: Controlled ingestion

Load an approved corpus, validate parser/OCR output, inspect lineage and verify tenant filters.

### Stage 3: Quality and latency evaluation

Run citation correctness, abstention, graph-lift, 100–200 page, scanned-document and concurrency tests.

### Stage 4: Security and operations review

Validate access roles, keys, deletion, restore, audit, monitoring, incident response and deployment boundary.

### Stage 5: Expansion decision

Choose shared logical isolation or a dedicated data plane and agree the production-readiness checklist.

<!-- PAGE 18 -->
## 18. Decision and next workshop

Aiwana is a strong candidate for a Zimyo-focused enterprise document-intelligence pilot because it combines agentic RAG foundations with a visible Captive Data control plane.

The immediate decision is not whether to promise universal production readiness. It is whether to run a bounded, measurable pilot that proves:

- answer quality and citation correctness,
- scanned and long-document behavior,
- latency under representative load,
- logical versus dedicated data-plane controls,
- retention and deletion evidence,
- and the exact Zimyo integration contract.

**Recommended next workshop:** architecture boundary, representative corpus, evaluation questions, identity/integration design, and production smoke prerequisites.

## Sources and evidence

- Repository evidence: `AIWANA_FEATURE_AUDIT.md`, `TECHNICAL_PROOF.md`, `PROPOSAL_CLAIM_REGISTER.md`.
- Screenshot index: `SCREENSHOT_MANIFEST.md`.
- Official public context: [Zimyo HR software](https://www.zimyo.com/hr-software/), [Zimyo employee self-service](https://www.zimyo.com/hr-software/employee-self-service/), [Zimyo attendance](https://www.zimyo.com/hr-software/attendance-management-system/).
