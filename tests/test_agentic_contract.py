from app.core.schemas import Citation, QueryResponse
from app.services.agentic import AgenticQueryEngine
from app.services.streaming import stream_completed_response


def test_agentic_contract_exposes_plan_tool_trace_and_verification():
    engine = AgenticQueryEngine()
    plan, trace, step = engine.build_contract(
        route_used="analytical",
        objective_profile="enterprise",
        analysis_mode="agentic",
        retrieval_strategy="hybrid",
        pipeline=[
            {"stage": "retriever", "tools": ["search_documents"]},
            {"stage": "tool_executor", "tools": ["search_graph", "verify_claims", "synthesize_answer"]},
        ],
        graph_enabled=True,
    )

    verification = engine.verify_answer(
        answer="The policy is supported. [Source: policy.pdf p.1 chunk-1]",
        citations=[
            Citation(
                document_id="doc-1",
                filename="policy.pdf",
                page_number=1,
                chunk_id="chunk-1",
                snippet="The policy is supported.",
            )
        ],
        confidence=0.82,
        final_context_size=1,
    )

    assert plan["run_mode"] == "agentic"
    assert "graph_enriched" in plan["strategy"]
    assert {item["tool_name"] for item in trace} >= {"search_documents", "search_graph", "verify_claims"}
    assert step.agent_name == "AgenticQueryEngine"
    assert verification["grounding_status"] == "grounded"


def test_stream_completed_response_emits_stage_token_and_final_events():
    response = QueryResponse(
        answer="Grounded answer.",
        citations=[],
        confidence=0.7,
        abstained=False,
        route_used="factual",
        retrieved_chunks=[],
        latency_ms={"retrieval": 1.0, "generation": 2.0},
        grounding_status="grounded",
    )

    body = "".join(stream_completed_response(response))

    assert "event: metadata" in body
    assert "event: stage" in body
    assert "event: token" in body
    assert "event: final" in body
    assert "Grounded answer." in body
