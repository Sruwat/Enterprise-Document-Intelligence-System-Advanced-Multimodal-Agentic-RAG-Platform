from pathlib import Path


def test_query_route_is_thin_and_engine_owned():
    route_text = Path("app/api/routes/query.py").read_text(encoding="utf-8")
    runtime_text = Path("app/services/agentic/runtime.py").read_text(encoding="utf-8")
    engine_text = Path("app/services/agentic/engine.py").read_text(encoding="utf-8")

    assert "def _query_documents_runtime" not in route_text
    assert "def _stream_query_native" not in route_text
    assert "executor=" not in route_text
    assert "def _query_documents_runtime" in runtime_text
    assert "def _stream_query_native" in runtime_text
    assert "_query_documents_runtime" in engine_text
    assert "_stream_query_native" in engine_text
