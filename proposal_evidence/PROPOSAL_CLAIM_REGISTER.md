# Proposal Claim Register

| Claim | Evidence | Status | Safe wording | Avoid |
|---|---|---|---|---|
| Private enterprise document intelligence | Private-only policy, tenant controls, Data Vault UI/tests | Working + tested policy capability | “Designed for private, governed enterprise document intelligence.” | “Absolutely private” |
| Captive Data lifecycle visibility | Data Vault overview, footprint, lineage, retention and purge code/tests | Working + tested in application fixtures | “Makes document processing layers visible and governable.” | “Every byte is always visible and deletable” |
| Tenant/workspace isolation | Auth/RBAC/Qdrant filter tests | Working + tested | “Logical tenant and workspace isolation is enforced in tested paths.” | “Zero leakage guaranteed” |
| Dedicated data plane | Tenant resolver, object-store abstraction, AWS runbook | Enterprise deployment option / foundation | “Dedicated deployment can be offered and validated per enterprise environment.” | “Already deployed per customer” |
| Verified purge | Deletion requests, purge verification, receipts and tests | Working + tested in local fixtures | “The product supports auditable purge requests and verification receipts.” | “Deletion from every backup is proven” |
| Vector and graph controls | Qdrant adapter, Postgres graph abstraction, lineage/footprint metadata | Implemented, needs live infrastructure validation | “Vector and graph layers are part of the governed data model.” | “Dedicated vector DB is live for every tenant” |
| Multi-format intelligence | Parser and ingestion tests for common formats | Working + tested | “Supports a broad document-ingestion foundation.” | “Every industry format is production-perfect” |
| 200-page processing | 200-page parse/chunk benchmark | Working + tested for parse/chunk path | “A synthetic 200-page document parsed to 270 chunks in local validation.” | “200-page scanned PDFs are guaranteed” |
| Agentic RAG | Agentic services, route ownership and tests | Working + tested in test/fallback paths | “Agentic planning, retrieval, verification and trace metadata are implemented.” | “Autonomous expert with no errors” |
| Graph memory lift | Graph proof tests; no live eval result in this audit | Implemented, needs live infrastructure validation | “Graph memory is an available proof path to validate in pilot data.” | “Graph materially improves every answer” |
| Zimyo fit | Official Zimyo pages describe HR, payroll, attendance, LMS, helpdesk, employee self-service and document/policy workflows | Commercial fit hypothesis | “A strong fit for HR policy, payroll, attendance, helpdesk and employee self-service knowledge workflows.” [Zimyo HR software](https://www.zimyo.com/hr-software/) | “Native integration already exists” |
| Security/compliance | Security controls and policy code; no external certification evidence | Roadmap / deployment validation required | “Security architecture and controls are implemented in part and require enterprise review.” | “SOC 2/HIPAA/GDPR certified” |
| Production readiness | Tests/build pass; live production smoke incomplete | Not yet fully proven | “Enterprise-pilot ready with a defined path to production validation.” | “100% production-ready” |
