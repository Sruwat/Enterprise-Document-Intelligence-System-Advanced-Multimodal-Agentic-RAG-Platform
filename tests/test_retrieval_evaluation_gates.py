import json

from app.core.schemas import AgentRun, AgentStep, Citation, ChunkRecord, EvidenceCanvas, QueryResponse
from app.services.evaluation.metrics import EvaluationService
from app.storage.metadata_store import MetadataStore


class _DummyEvalLogger:
    pass


def _response(page_number=4, *, abstained=False):
    chunk = ChunkRecord(
        chunk_id="chunk-1",
        document_id="doc-1",
        workspace_id="default",
        filename="contract.pdf",
        page_number=page_number,
        text="Termination requires 30 days notice.",
        token_count=5,
    )
    return QueryResponse(
        answer="Termination requires 30 days notice.",
        citations=[
            Citation(
                document_id="doc-1",
                filename="contract.pdf",
                page_number=page_number,
                chunk_id="chunk-1",
                snippet="Termination requires 30 days notice.",
            )
        ],
        confidence=0.9,
        abstained=abstained,
        route_used="factual",
        retrieved_chunks=[chunk],
        latency_ms={},
    )


def test_seeded_evaluation_computes_recall_citation_and_pass_rate(tmp_path):
    dataset = tmp_path / "eval.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "query": "What is the termination notice?",
                    "expected_answer": "30 days",
                    "supporting_document_reference": {"document_id": "doc-1", "page_number": 4},
                    "expected_behavior": "answer",
                    "category": "legal",
                }
            ]
        ),
        encoding="utf-8",
    )
    store = MetadataStore(tmp_path / "metadata.db")
    service = EvaluationService(_DummyEvalLogger(), store, query_runner=lambda _case: _response())

    result = service.run_seeded_evaluation(str(dataset))
    gates = service.launch_gates(min_queries=0)

    assert result["status"] == "completed"
    assert result["metrics"]["pass_rate"] == 1.0
    assert result["metrics"]["citation_page_accuracy"] == 1.0
    assert any(check["name"] == "seeded_benchmark_pass_rate" and check["status"] == "ok" for check in gates["checks"])


def test_seeded_evaluation_gate_blocks_wrong_citation_page(tmp_path):
    dataset = tmp_path / "eval.json"
    dataset.write_text(
        '[{"query":"q","expected_answer":"30 days","supporting_document_reference":{"document_id":"doc-1","page_number":4},"expected_behavior":"answer"}]',
        encoding="utf-8",
    )
    store = MetadataStore(tmp_path / "metadata.db")
    service = EvaluationService(_DummyEvalLogger(), store, query_runner=lambda _case: _response(page_number=9))

    service.run_seeded_evaluation(str(dataset))
    gates = service.launch_gates(min_queries=0)

    assert gates["status"] == "blocked"
    assert any(check["name"] == "seeded_benchmark_pass_rate" and check["status"] == "blocker" for check in gates["checks"])


def test_seeded_evaluation_scores_launch_category_requirements(tmp_path):
    dataset = tmp_path / "eval.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "query": "Graph kya batao",
                    "expected_answer": "chart",
                    "supporting_document_reference": {"document_id": "doc-1", "page_number": 4},
                    "expected_behavior": "answer",
                    "category": "multilingual",
                    "expected_language": "hinglish",
                    "expected_tools": ["search_documents"],
                    "expected_agent_steps": ["RetrievalAgent"],
                    "requires_visual_evidence": True,
                    "min_confidence": 0.8,
                }
            ]
        ),
        encoding="utf-8",
    )
    store = MetadataStore(tmp_path / "metadata.db")
    chunk = ChunkRecord(chunk_id="chunk-1", document_id="doc-1", workspace_id="default", filename="doc.pdf", page_number=4, text="chart evidence", token_count=2)
    response = QueryResponse(
        answer="chart evidence",
        citations=[Citation(document_id="doc-1", filename="doc.pdf", page_number=4, chunk_id="chunk-1", snippet="chart evidence")],
        confidence=0.9,
        abstained=False,
        route_used="visual_question",
        retrieved_chunks=[chunk],
        latency_ms={},
        answer_language="hinglish",
        visual_cards=[{"evidence_id": "v1", "document_id": "doc-1", "filename": "doc.pdf", "page_number": 4, "visual_type": "chart", "interpretation": "chart", "plain_language_explanation": "chart"}],
        evidence_canvas=EvidenceCanvas(
            citations=[Citation(document_id="doc-1", filename="doc.pdf", page_number=4, chunk_id="chunk-1", snippet="chart evidence")],
            visual_cards=[{"evidence_id": "v1", "document_id": "doc-1", "filename": "doc.pdf", "page_number": 4, "visual_type": "chart", "interpretation": "chart", "plain_language_explanation": "chart"}],
            agent_steps=[
                AgentStep(
                    step_id="s1",
                    agent_name="RetrievalAgent",
                    action="retrieve",
                    metadata={"tool_calls": [{"tool_name": "search_documents"}]},
                )
            ],
        ),
        agent_run=AgentRun(
            run_id="run-1",
            workspace_id="default",
            steps=[AgentStep(step_id="s1", agent_name="RetrievalAgent", action="retrieve", metadata={"tool_calls": [{"tool_name": "search_documents"}]})],
            created_at=__import__("datetime").datetime.utcnow(),
        ),
    )
    service = EvaluationService(_DummyEvalLogger(), store, query_runner=lambda _case: response)

    result = service.run_seeded_evaluation(str(dataset))

    assert result["metrics"]["pass_rate"] == 1.0
    assert result["metrics"]["multilingual_accuracy"] == 1.0
    assert result["metrics"]["tool_selection_accuracy"] == 1.0


def test_launch_gates_block_missing_required_dataset_categories(tmp_path):
    dataset = tmp_path / "eval.json"
    dataset.write_text('[{"query":"q","category":"citation"}]', encoding="utf-8")
    store = MetadataStore(tmp_path / "metadata.db")
    service = EvaluationService(_DummyEvalLogger(), store)

    gates = service.launch_gates(dataset_path=str(dataset), min_queries=0, require_dataset_coverage=True)

    assert gates["status"] == "blocked"
    coverage = next(check for check in gates["checks"] if check["name"] == "launch_dataset_coverage")
    assert "agent_orchestration" in coverage["missing_categories"]
