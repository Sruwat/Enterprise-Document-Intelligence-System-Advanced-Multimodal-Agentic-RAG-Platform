from pathlib import Path

import pytest

from app.services.ingestion.embedder import SentenceTransformerEmbeddingProvider


def test_embedder_raises_clear_error_when_local_model_path_is_missing():
    provider = SentenceTransformerEmbeddingProvider(Path("./models/does-not-exist"))

    with pytest.raises(FileNotFoundError, match="Embedding model directory not found"):
        provider.embed_query("startup validation")
