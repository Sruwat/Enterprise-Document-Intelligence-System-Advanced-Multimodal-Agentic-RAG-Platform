from datetime import datetime

from app.core.schemas import AgentRun, AgentStep, QueryRequest, QueryResponse, UserRecord
from app.services.orchestrator.agent_orchestrator import AgentOrchestrator


class _Store:
    def __init__(self):
        self.runs = []

    def log_agent_run(self, run):
        self.runs.append(run)


class _Redis:
    def __init__(self):
        self.states = {}

    def set_agent_state(self, run_id, payload, ttl_seconds=21600):
        self.states[run_id] = payload


def test_agent_orchestrator_finalizes_durable_run_and_redis_state():
    orchestrator = AgentOrchestrator()
    request = QueryRequest(question="What is the termination risk?", workspace_id="workspace-1", session_id="session-1", objective_profile="legal", analysis_mode="agentic")
    user = UserRecord(user_id="user-1", tenant_id="tenant-1", email="user@example.com", created_at=datetime.utcnow())
    redis = _Redis()
    store = _Store()
    run_id = orchestrator.start_run(request, user, redis_service=redis)
    response = QueryResponse(
        answer="Termination requires notice. [Source: contract.pdf p.1]",
        citations=[],
        confidence=0.82,
        abstained=False,
        route_used="analytical",
        retrieved_chunks=[],
        latency_ms={},
        final_context_size=1,
        retrieval_metadata={"retrieval_strategy": "hybrid_clause_aware"},
        agent_run=AgentRun(
            run_id="agent-run-1",
            session_id="session-1",
            workspace_id="workspace-1",
            objective_profile="legal",
            analysis_mode="agentic",
            steps=[
                AgentStep(
                    step_id="step-1",
                    agent_name="ContextAgent",
                    action="build_user_task_context",
                    output_summary="Loaded context.",
                )
            ],
            created_at=datetime.utcnow(),
        ),
    )

    finalized = orchestrator.finalize_response(
        orchestration_run_id=run_id,
        request=request,
        response=response,
        user=user,
        metadata_store=store,
        redis_service=redis,
    )

    assert finalized.agent_run is not None
    assert finalized.agent_run.steps[-1].agent_name == "AgentOrchestrator"
    assert finalized.agent_run.metadata["orchestration_run_id"] == run_id
    assert store.runs[-1].run_id == "agent-run-1"
    assert redis.states[run_id]["status"] == "completed"
    assert redis.states[run_id]["step_count"] == 2


def test_agent_orchestrator_records_failed_state():
    orchestrator = AgentOrchestrator()
    request = QueryRequest(question="Hello", workspace_id="workspace-1")
    redis = _Redis()

    run_id = orchestrator.start_run(request, UserRecord(user_id="u", email="u@example.com", created_at=datetime.utcnow()), redis_service=redis)
    orchestrator.fail_run(orchestration_run_id=run_id, request=request, error=RuntimeError("boom"), redis_service=redis)

    assert redis.states[run_id]["status"] == "failed"
    assert redis.states[run_id]["error"] == "boom"


def test_agent_orchestrator_plans_tool_pipeline_and_blocks_weak_answer():
    orchestrator = AgentOrchestrator()
    request = QueryRequest(question="Analyze the contract risk", workspace_id="default", objective_profile="legal", analysis_mode="agentic")

    pipeline, step = orchestrator.plan_pipeline(
        request=request,
        route_used="analytical",
        retrieval_plan={"strategy": "hybrid_clause_aware", "top_k": 12, "use_graph": True},
        needs_graph=True,
    )

    tools = {tool for stage in pipeline for tool in stage["tools"]}
    assert step.agent_name == "PlannerAgent"
    assert {"search_documents", "search_graph", "extract_clauses", "verify_claims", "synthesize_answer"} <= tools

    force_abstain, confidence, verifier_step = orchestrator.verification_step(
        answer="The contract definitely guarantees a win.",
        confidence=0.9,
        citations=[],
        final_context_size=1,
        route_used="analytical",
        objective_profile="legal",
        min_confidence=0.42,
    )

    assert force_abstain is True
    assert confidence == 0.0
    assert verifier_step.agent_name == "VerifierAgent"
    assert "missing_citations" in verifier_step.metadata["reasons"]
