from app.services.huggingface import HuggingFaceProviderRegistry


def test_huggingface_registry_reports_task_providers(tmp_path):
    registry = HuggingFaceProviderRegistry(enabled=True, cache_dir=tmp_path)

    status = registry.status()

    assert status["enabled"] is True
    assert status["provider_count"] >= 8
    assert status["providers"]["embedding"]["model_id"] == "BAAI/bge-m3"
    assert status["providers"]["reranking"]["model_id"] == "BAAI/bge-reranker-v2-m3"
    assert status["providers"]["evidence_checking"]["enabled"] is True


def test_huggingface_registry_has_safe_offline_classification_fallback(tmp_path):
    registry = HuggingFaceProviderRegistry(enabled=False, cache_dir=tmp_path)

    legal = registry.classify_document("This agreement has a termination clause and liability cap.")
    enterprise = registry.classify_document("Audit controls and compliance policy are required.")

    assert legal["label"] == "legal"
    assert enterprise["label"] == "enterprise"
    assert legal["provider"] == "heuristic_hf_registry_fallback"

