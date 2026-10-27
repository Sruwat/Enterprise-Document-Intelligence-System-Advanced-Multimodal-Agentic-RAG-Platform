# Proposal Asset Manifest

Recommended source-pack assembly for a 16-18 page client proposal. All claims must use `PROPOSAL_CLAIM_REGISTER.md`.

| Page | Purpose | Asset | Evidence label |
|---:|---|---|---|
| 01 | Cover | Aiwana x Zimyo title, Captive Data subtitle | Proposal framing |
| 02 | Executive thesis | One-page value statement | Commercial hypothesis |
| 03 | Zimyo context | Official HR/payroll/attendance/helpdesk/document categories | Public-source context |
| 04 | The problem | Data sprawl, policy retrieval, audit pressure | Discovery hypothesis |
| 05 | Captive Data | Before/after lifecycle diagram | Architecture target + current controls |
| 06 | Product overview | `screens/01_dashboard.png` | Working UI shell |
| 07 | Ingestion intelligence | `screens/02_document_upload.png`, `screens/15_industry_packs.png` | Working surface; tenant empty |
| 08 | Agentic answers | `screens/03_chat_with_citations.png`, `screens/16_query_modes.png` | UI contract; no populated answer proof |
| 09 | Evidence and graph | `screens/04_evidence_view.png`, `screens/08_vector_index_chunks.png` | Implemented path; live lift pending |
| 10 | Data Vault | `screens/05_data_vault_overview.png`, `screens/06_document_data_footprint.png` | Captive Data controls |
| 11 | Lineage and retention | `screens/07_data_lineage.png`, `screens/09_privacy_processing_boundary.png`, `screens/10_retention_policy.png` | Control-plane evidence |
| 12 | Deletion | `screens/11_delete_everywhere.png`, `screens/12_deletion_verification.png`, `screens/13_deletion_receipt.png` | Workflow surface; receipt fixtures tested |
| 13 | Governance | `screens/14_admin_rbac.png` | Admin/RBAC surface |
| 14 | Deployment choices | Shared logical isolation vs dedicated data plane | Foundation/option |
| 15 | Use cases | HR policy, payroll support, attendance, helpdesk, LMS, compliance | Pilot hypotheses |
| 16 | Validation plan | Tests, 200-page benchmark, live smoke and security gates | Technical proof |
| 17 | Pilot roadmap | Discover, connect, validate, expand | Proposed plan |
| 18 | Commercial close | Decision, inputs, next workshop | Call to action |

## Visual treatment

Use screenshots as labeled product evidence with a small footer: “Local authenticated capture; capability and production status are defined in the evidence register.” Do not retouch empty states into populated data.
