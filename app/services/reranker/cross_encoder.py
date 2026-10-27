from __future__ import annotations

import time
from pathlib import Path

from app.core.schemas import ChunkRecord


class CrossEncoderReranker:
    def __init__(self, model_path: str | Path, max_candidates: int = 20, batch_size: int = 16, timeout_seconds: float = 3.0) -> None:
        self.model_path = Path(model_path)
        self.model_name = str(self.model_path)
        self.max_candidates = max_candidates
        self.batch_size = batch_size
        self.timeout_seconds = timeout_seconds
        self._model = None
        self.last_status: dict = {"status": "not_run"}

    def _load(self):
        if self._model is None:
            if not self.model_path.exists():
                raise FileNotFoundError(
                    f"Reranker model directory not found: {self.model_path}. "
                    "Download BAAI/bge-reranker-base into the configured local path before starting the app."
                )
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(str(self.model_path), local_files_only=True)
        return self._model

    def warmup(self) -> None:
        self._load()

    def status(self) -> dict:
        try:
            self._load()
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
            "max_candidates": self.max_candidates,
            "batch_size": self.batch_size,
            "timeout_seconds": self.timeout_seconds,
            "last_run": self.last_status,
        }

    def rerank(self, question: str, chunks: list[ChunkRecord], top_n: int) -> list[ChunkRecord]:
        if not chunks:
            return []
        started = time.perf_counter()
        bounded = chunks[: max(1, min(len(chunks), self.max_candidates, top_n if top_n > 0 else self.max_candidates))]
        model = self._load()
        pairs = [[question, chunk.text[:1800]] for chunk in bounded]
        try:
            scores = model.predict(pairs, batch_size=self.batch_size)
        except TypeError:
            scores = model.predict(pairs)
        elapsed = time.perf_counter() - started
        if self.timeout_seconds and elapsed > self.timeout_seconds:
            self.last_status = {
                "status": "timeout_degraded",
                "elapsed_ms": round(elapsed * 1000, 2),
                "candidate_count": len(bounded),
                "returned": "fused_order",
            }
            return chunks[:top_n]
        reranked: list[ChunkRecord] = []
        for chunk, score in zip(bounded, scores):
            chunk.rerank_score = float(score)
            reranked.append(chunk)
        reranked.sort(key=lambda item: item.rerank_score or 0.0, reverse=True)
        self.last_status = {
            "status": "ok",
            "elapsed_ms": round(elapsed * 1000, 2),
            "candidate_count": len(bounded),
            "batch_size": self.batch_size,
        }
        return reranked[:top_n]


class DisabledReranker:
    def __init__(self, reason: str = "disabled by configuration") -> None:
        self.model_path = Path(".")
        self.model_name = "disabled"
        self.reason = reason

    def warmup(self) -> None:
        return None

    def status(self) -> dict:
        return {
            "status": "disabled",
            "path": None,
            "loaded": False,
            "detail": self.reason,
        }

    def rerank(self, question: str, chunks: list[ChunkRecord], top_n: int) -> list[ChunkRecord]:
        return chunks[:top_n]
