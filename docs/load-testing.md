# Load Testing

Aiwana should be load tested before production launch.

Suggested scenarios:

- health/readiness
- login/session validation
- workspace document list
- RAG query
- streaming query
- upload initiation
- ingestion job status

Suggested tiers:

- 10 users
- 50 users
- 100 users

Report p50, p95, p99, throughput, and error rate. Do not publish production performance claims without running these tests against the target deployment.

