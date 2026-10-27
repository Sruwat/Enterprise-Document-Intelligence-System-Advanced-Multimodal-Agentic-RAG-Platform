# Tenant Isolation

Aiwana uses defense in depth:

- application-level authentication
- workspace membership checks
- RBAC permissions
- tenant/workspace identifiers on durable rows
- Postgres Row Level Security policies
- Qdrant payload filters
- Redis tenant/workspace key namespaces
- tenant/workspace file path namespaces

Standard SaaS mode uses a shared Postgres database and shared Qdrant collection with strict tenant/workspace filters. Enterprise mode can move to dedicated databases, per-tenant Qdrant collections, and dedicated storage buckets. Regulated/on-prem mode should run inside the customer VPC or on-prem environment with private LLMs.

Postgres RLS uses transaction-local settings:

```sql
SET LOCAL app.current_tenant_id = 'tenant-id';
SET LOCAL app.current_workspace_id = 'workspace-id';
```

Application authorization remains mandatory even when RLS is enabled.

