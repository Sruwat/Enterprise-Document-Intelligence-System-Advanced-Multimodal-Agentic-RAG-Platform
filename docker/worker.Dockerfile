FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_REQUIRE_HASHES=0

WORKDIR /workspace
COPY requirements-backend.txt .
RUN pip install --upgrade --no-cache-dir pip setuptools wheel
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-backend.txt
COPY models /app/models
COPY . .

CMD ["python", "-m", "tools.worker"]
