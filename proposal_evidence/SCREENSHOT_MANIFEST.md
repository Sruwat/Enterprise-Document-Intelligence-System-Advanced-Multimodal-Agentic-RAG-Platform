# Screenshot Manifest

Captured with `tools/capture_proposal_screens.mjs` against the local Next.js app. Files are under `proposal_evidence/screens/`.

**Capture caveat:** the authenticated demo account created a separate workspace, while the UI remained on `Default workspace`. The screenshots therefore show honest empty/degraded states rather than populated document evidence. A Next development overlay badge (`1 Issue`) is visible in the capture. These are product-surface screenshots, not production capability proof.

| # | File | Surface | Evidence status |
|---:|---|---|---|
| 01 | `screens/01_dashboard.png` | Dashboard | Available; authenticated shell and empty metrics |
| 02 | `screens/02_document_upload.png` | Sources/upload | Available; upload surface rendered; no indexed document proof |
| 03 | `screens/03_chat_with_citations.png` | Chat | Available; empty/degraded chat state; no populated citation proof |
| 04 | `screens/04_evidence_view.png` | Evidence | Available; empty evidence state |
| 05 | `screens/05_data_vault_overview.png` | Data Vault overview | Available; Captive Data controls and empty-state metrics |
| 06 | `screens/06_document_data_footprint.png` | Document footprint | Available; empty/degraded state |
| 07 | `screens/07_data_lineage.png` | Data lineage | Available; empty/degraded state |
| 08 | `screens/08_vector_index_chunks.png` | Vector/chunk view | Available; empty/degraded state |
| 09 | `screens/09_privacy_processing_boundary.png` | Privacy boundary | Available; policy surface rendered |
| 10 | `screens/10_retention_policy.png` | Retention policy | Available; policy controls rendered |
| 11 | `screens/11_delete_everywhere.png` | Delete workflow | Available; control surface rendered; no live purge proof |
| 12 | `screens/12_deletion_verification.png` | Deletion verification | Available; empty/degraded state |
| 13 | `screens/13_deletion_receipt.png` | Deletion receipt | Available; empty/degraded state |
| 14 | `screens/14_admin_rbac.png` | Admin/RBAC | Available; admin shell, readiness unknown, no populated keys |
| 15 | `screens/15_industry_packs.png` | Industry packs | Available; catalog surface rendered |
| 16 | `screens/16_query_modes.png` | Query modes | Available; query mode surface rendered |

## Proposal usage

Safe: use 01, 05, 09, 10, 14, 15 and 16 as product UI evidence.  
Use 06–13 only as concept/control-plane surfaces with an explicit “illustrative local capture / empty tenant” label.  
Do not caption any screenshot as proof of successful indexing, citations, graph lift, purge completion, or live production health.
