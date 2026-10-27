from pathlib import Path

import pytest

from app.services.evaluation.metrics import EvaluationService
from app.storage.metadata_store import MetadataStore


class _DummyEvalLogger:
    pass


def test_evaluation_loader_supports_json_array_and_jsonl(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    service = EvaluationService(_DummyEvalLogger(), store)

    array_path = tmp_path / "array.json"
    array_path.write_text('[{"query":"q1"},{"query":"q2"}]', encoding="utf-8")
    jsonl_path = tmp_path / "records.jsonl"
    jsonl_path.write_text('{"query":"q1"}\n{"query":"q2"}\n', encoding="utf-8")

    assert service.run_seeded_evaluation(str(array_path))["dataset_size"] == 2
    assert service.run_seeded_evaluation(str(jsonl_path))["dataset_size"] == 2


def test_evaluation_loader_raises_clear_error_for_invalid_format(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    service = EvaluationService(_DummyEvalLogger(), store)
    invalid_path = tmp_path / "invalid.txt"
    invalid_path.write_text("{not-json}", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected either a JSON array or JSONL"):
        service.run_seeded_evaluation(str(invalid_path))


def test_metrics_snapshot_returns_valid_json_shape(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    service = EvaluationService(_DummyEvalLogger(), store)

    snapshot = service.metrics_snapshot()

    assert snapshot["total_queries"] == 0
    assert "avg_confidence" in snapshot
    assert "abstention_rate" in snapshot
    assert isinstance(snapshot["metrics"], dict)


def test_launch_gates_block_without_enough_grounded_queries(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    service = EvaluationService(_DummyEvalLogger(), store)

    gates = service.launch_gates(min_queries=1)

    assert gates["status"] == "blocked"
    assert any(check["name"] == "minimum_query_volume" for check in gates["checks"])
