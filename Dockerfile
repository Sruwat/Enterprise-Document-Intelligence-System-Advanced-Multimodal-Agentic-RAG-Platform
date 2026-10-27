FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_REQUIRE_HASHES=0 \
    HF_HOME=/models/huggingface \
    EMBEDDING_MODEL=BAAI/bge-m3 \
    EMBEDDING_MODEL_PATH=/app/models/bge-m3 \
    RERANKER_MODEL=BAAI/bge-reranker-v2-m3 \
    RERANKER_MODEL_PATH=/app/models/bge-reranker-v2-m3 \
    QDRANT_COLLECTION=aiwana_chunks_v2 \
    ENABLE_NAMED_VECTORS=true \
    ENABLE_PERSISTENT_MEMORY=true

WORKDIR /workspace
COPY requirements-backend.txt .
RUN pip install --upgrade --no-cache-dir pip setuptools wheel
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-backend.txt
COPY models /app/models
COPY app /workspace/app
COPY data/eval_dataset_novatech.json /workspace/data/eval_dataset_novatech.json
COPY data/sample_report.pdf /workspace/data/sample_report.pdf
COPY evaluate.py /workspace/evaluate.py
COPY README.md /workspace/README.md

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
