import sys
import types
from pathlib import Path

import pytest

from app.core.schemas import ChunkRecord
from app.services.reranker.cross_encoder import CrossEncoderReranker


def test_reranker_raises_clear_error_when_local_model_path_is_missing():
    reranker = CrossEncoderReranker(Path("./models/does-not-exist"))

    with pytest.raises(FileNotFoundError, match="Reranker model directory not found"):
        reranker.rerank(
            "question",
            [ChunkRecord(chunk_id="1", document_id="d", filename="f", page_number=1, text="hello", metadata={})],
            top_n=1,
        )


def test_reranker_loads_from_local_path_only(tmp_path, monkeypatch):
    model_path = tmp_path / "bge-reranker-base"
    model_path.mkdir()
    calls = {}

    class FakeCrossEncoder:
        def __init__(self, model_name, local_files_only):
            calls["model_name"] = model_name
            calls["local_files_only"] = local_files_only

        def predict(self, pairs):
            return [0.99 for _ in pairs]

    fake_module = types.SimpleNamespace(CrossEncoder=FakeCrossEncoder)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    reranker = CrossEncoderReranker(model_path)
    result = reranker.rerank(
        "question",
        [ChunkRecord(chunk_id="1", document_id="d", filename="f", page_number=1, text="hello", metadata={})],
        top_n=1,
    )

    assert calls["model_name"] == str(model_path)
    assert calls["local_files_only"] is True
    assert result[0].rerank_score == 0.99
