# Large Document Ingestion

Large documents should be processed asynchronously:

```text
upload -> validate -> tenant-scoped storage -> ingestion job -> worker -> parse/OCR/chunk/embed/index -> ready
```

Current target architecture supports text PDFs, scanned PDFs, DOCX, CSV, XLSX, PPTX, images, TXT, and Markdown. For 200-page scanned PDFs, production validation must prove page-level OCR performance in the target environment before promising reliability.

Required production behavior:

- do not keep HTTP requests open for full indexing
- persist job progress
- process OCR page-by-page
- record OCR confidence/failures
- retry failed jobs
- avoid duplicate document/chunk/vector creation on retry
- batch embeddings with `EMBEDDING_BATCH_SIZE`

