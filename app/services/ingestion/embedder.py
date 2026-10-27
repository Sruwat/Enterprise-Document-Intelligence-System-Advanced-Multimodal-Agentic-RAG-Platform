from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class EmbeddingProvider(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


class SentenceTransformerEmbeddingProvider:
    def __init__(self, model_path: str | Path, batch_size: int = 32) -> None:
        self.model_path = Path(model_path)
        self.batch_size = batch_size
        self._model = None

    def _load(self):
        if self._model is None:
            if not self.model_path.exists():
                raise FileNotFoundError(
                    f"Embedding model directory not found: {self.model_path}. "
                    "Download BAAI/bge-small-en-v1.5 into the configured local path before starting the app."
                )
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(str(self.model_path), local_files_only=True)
        return self._model

    def status(self) -> dict:
        try:
            probe = self.embed_query("health probe")
        except Exception as exc:
            return {
                "status": "error",
                "path": str(self.model_path),
                "loaded": False,
                "detail": str(exc),
            }
        return {
            "status": "ok",
            "path": str(self.model_path),
            "loaded": True,
            "dimension": len(probe),
        }

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        vectors = model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True)
        return [vector.tolist() for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        model = self._load()
        vector = model.encode([text], normalize_embeddings=True)[0]
        return vector.tolist()


class BgeM3EmbeddingProvider(SentenceTransformerEmbeddingProvider):
    """BGE-M3 provider.

    Uses FlagEmbedding when available so later sparse/multi-vector modes can be
    enabled without changing callers. Falls back to SentenceTransformer dense
    embeddings for offline/local compatibility.
    """

    expected_dimension = 1024

    def __init__(self, model_path: str | Path, batch_size: int = 32, enable_sparse: bool = False) -> None:
        super().__init__(model_path, batch_size)
        self.enable_sparse = enable_sparse
        self._flag_model = None
        self._last_sparse_vectors: list[dict[int, float]] = []

    def _load_flag_model(self):
        if self._flag_model is None:
            if not self.model_path.exists():
                raise FileNotFoundError(
                    f"BGE-M3 model directory not found: {self.model_path}. "
                    "Download BAAI/bge-m3 into the configured local path before starting the v2 retrieval profile."
                )
            from FlagEmbedding import BGEM3FlagModel

            self._flag_model = BGEM3FlagModel(str(self.model_path), use_fp16=False)
        return self._flag_model

    def _encode(self, texts: list[str], *, return_sparse: bool | None = None) -> tuple[list[list[float]], list[dict[int, float]]]:
        sparse_requested = self.enable_sparse if return_sparse is None else return_sparse
        try:
            model = self._load_flag_model()
            result = model.encode(texts, batch_size=self.batch_size, return_dense=True, return_sparse=sparse_requested, return_colbert_vecs=False)
            vectors = result["dense_vecs"]
            dense_vectors = [vector.tolist() if hasattr(vector, "tolist") else list(vector) for vector in vectors]
            sparse_vectors = self._normalize_sparse_vectors(result.get("lexical_weights", [])) if sparse_requested else []
            return dense_vectors, sparse_vectors
        except ImportError:
            return super().embed_documents(texts), []

    def status(self) -> dict:
        base = super().status()
        base["expected_dimension"] = self.expected_dimension
        base["profile"] = "bge-m3"
        base["sparse_enabled"] = self.enable_sparse
        if self.enable_sparse:
            base["sparse_available"] = self._sparse_available()
        return base

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        dense, sparse = self._encode(texts)
        self._last_sparse_vectors = sparse
        return dense

    def embed_query(self, text: str) -> list[float]:
        dense, sparse = self._encode([text])
        self._last_sparse_vectors = sparse
        return dense[0]

    def embed_sparse_documents(self, texts: list[str]) -> list[dict[int, float]]:
        if not self.enable_sparse or not texts:
            return []
        _dense, sparse = self._encode(texts, return_sparse=True)
        return sparse

    def embed_sparse_query(self, text: str) -> dict[int, float]:
        if not self.enable_sparse:
            return {}
        sparse = self.embed_sparse_documents([text])
        return sparse[0] if sparse else {}

    def pop_last_sparse_vectors(self) -> list[dict[int, float]]:
        vectors = self._last_sparse_vectors
        self._last_sparse_vectors = []
        return vectors

    def _sparse_available(self) -> bool:
        try:
            return bool(self.embed_sparse_query("sparse health probe"))
        except Exception:
            return False

    @staticmethod
    def _normalize_sparse_vectors(raw_vectors: Any) -> list[dict[int, float]]:
        normalized: list[dict[int, float]] = []
        for raw in raw_vectors or []:
            if isinstance(raw, dict):
                normalized.append({int(index): float(value) for index, value in raw.items() if float(value) != 0.0})
                continue
            if hasattr(raw, "items"):
                normalized.append({int(index): float(value) for index, value in raw.items() if float(value) != 0.0})
                continue
            normalized.append({})
        return normalized
