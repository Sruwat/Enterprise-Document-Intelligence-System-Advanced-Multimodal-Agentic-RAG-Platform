# Aiwana Technical Proof Register

**As of:** 2026-09-08

## Commands and observed results

| Command | Result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest -q` | `167 passed, 6 warnings` in approximately `166.32s` |
| `.\.venv\Scripts\python.exe -m pytest tests\test_captive_data_controls.py tests\test_query_modes_data_vault.py -q` | `8 passed` in approximately `7.49s` |
| `.\.venv\Scripts\python.exe -m compileall app tests tools -q` | Passed |
| `cd frontend; npm run build` | Passed; Next production build generated routes `/`, `/admin`, `/chat`, `/data-vault`, `/evidence`, `/settings`, `/sources` |
| `.\.venv\Scripts\python.exe tools\benchmark_long_documents.py` | Passed; `200` pages parsed into `270` chunks; parse `33429.64 ms`; chunk `23.33 ms`; OCR disabled |

## Long-document evidence

The generated record is `data/benchmarks/long_document.json`. It demonstrates the parser/chunker path on the synthetic 200-page multimodal fixture `data/validation_latency/aiwana_200_page_multimodal_benchmark.pdf`.

It does **not** include live embedding, Qdrant, graph, OCR, or end-to-end answer timings. It cannot support a “200-page scanned PDFs always work” or latency-SLA claim.

## Historical query telemetry

The repository's existing query log sample contained 81 records:

- total latency average: `31,152.81 ms`
- total latency p50: `10,946.05 ms`
- total latency p95: `86,332.53 ms`
- retrieval p50: `191.61 ms`
- rerank p50: `9,050.84 ms`
- rerank p95: `51,002 ms`
- multistep p95: `119,136.26 ms`

These are historical application telemetry, not a controlled benchmark. They show why latency must be a commercial qualification item rather than a marketing promise.

## Local runtime proof

A disposable local backend was started successfully on `http://127.0.0.1:8000` using SQLite metadata and local file-backed Qdrant fallback. Startup loaded the local BGE-M3 embedding model at dimension 1024 and the local reranker. The demo workspace contained zero documents.

This proves the application can start in a local fallback profile. It does not prove a production stack: Postgres, Redis, a Qdrant server, external/private LLM streaming, worker durability, and object storage were not all live together in this audit.

## Security and data-control proof

Automated coverage passed for authentication defaults, workspace scoping, RBAC, tenant Qdrant filters, Data Vault controls, deletion requests, lineage, query modes, graph proof, worker foundations, parser behavior, backup tooling, and Hugging Face registry behavior. The exact tests are referenced in `AIWANA_FEATURE_AUDIT.md`.

## Unsupported claims intentionally excluded

No evidence was found in this audit for: zero leakage, absolute privacy, “data never leaves your VPC,” SOC 2/HIPAA/GDPR certification, a live AWS deployment, sustained concurrency capacity, a live 200-page scanned OCR SLA, or a native Zimyo connector.
