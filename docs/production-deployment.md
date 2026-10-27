# Production Deployment

Production stack:

- frontend
- backend
- worker
- Postgres
- Redis
- Qdrant
- private object storage
- optional private LLM

Before launch:

1. Set `.env.production`.
2. Configure Google OAuth.
3. Configure `AUTH_SECRET`.
4. Run migrations.
5. Run backend tests.
6. Run frontend build.
7. Run launch evals.
8. Run smoke tests with auth.
9. Verify backup/restore drill.

For sensitive enterprises, deploy inside the customer VPC/on-prem and use `LLM_PRIVACY_MODE=private_only`.

