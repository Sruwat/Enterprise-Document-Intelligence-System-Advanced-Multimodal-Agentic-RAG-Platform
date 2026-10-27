from app.core.schemas import Citation, ChunkRecord
from app.services.agents.evidence_agent import EvidenceAgent
from app.services.agents.objective_agents import EnterpriseAgent, LegalAgent, StudyAgent
from app.services.agents.retrieval_agent import RetrievalAgent


def test_retrieval_agent_expands_legal_agentic_depth():
    plan, step = RetrievalAgent().plan(
        route_used="analytical",
        objective_profile="legal",
        analysis_mode="agentic",
        requested_top_k=5,
        has_visual_request=False,
    )
    assert plan["strategy"] == "hybrid_clause_aware"
    assert plan["top_k"] >= 12
    assert step.agent_name == "RetrievalAgent"


def test_retrieval_agent_uses_document_memory_for_structured_docs():
    plan, _step = RetrievalAgent().plan(
        route_used="factual",
        objective_profile="research",
        analysis_mode="quick",
        requested_top_k=5,
        has_visual_request=False,
        context={"document_memories": [{"metadata": {"table_count": 2, "chart_count": 1}}]},
    )

    assert plan["top_k"] >= 10
    assert plan["use_table_visual_boost"] is True


def test_evidence_agent_builds_canvas_with_why_trace():
    chunk = ChunkRecord(
        chunk_id="chunk-1",
        document_id="doc-1",
        filename="contract.pdf",
        page_number=4,
        text="Termination requires thirty days notice.",
        token_count=5,
    )
    citation = Citation(
        document_id="doc-1",
        filename="contract.pdf",
        page_number=4,
        chunk_id="chunk-1",
        snippet="Termination requires thirty days notice.",
    )
    canvas, step = EvidenceAgent().build_canvas(
        chunks=[chunk],
        citations=[citation],
        confidence=0.81,
        route_used="factual",
        include_visual=False,
        answer_preview="The contract requires thirty days notice.",
    )
    assert canvas.confidence == 0.81
    assert canvas.citations[0].page_number == 4
    assert "page(s): 4" in canvas.why_this_answer
    assert step.agent_name == "EvidenceAgent"


def test_legal_agent_extracts_obligations_and_missing_clauses():
    chunk = ChunkRecord(
        chunk_id="c1",
        document_id="d1",
        filename="contract.docx",
        page_number=1,
        text="Agreement between NovaTech Ltd and Suryagram Trust. Payment: Customer shall pay invoices within 30 days. Termination may occur after breach.",
    )

    note, step = LegalAgent().annotate("Find risks", [chunk])

    assert "Candidate obligations" in note
    assert step.metadata["obligations"]
    assert step.metadata["parties"]
    assert step.metadata["obligation_timeline"][0]["due"] == "30 days"
    assert "indemnity" in step.metadata["missing_standard_clauses"]


def test_study_and_enterprise_agents_emit_structured_metadata():
    table_chunk = ChunkRecord(
        chunk_id="c2",
        document_id="d2",
        filename="report.pdf",
        page_number=2,
        text="Research Findings show policy compliance.",
        content_type="table",
        section_path=["Research Findings"],
    )

    _study_note, study_step = StudyAgent().annotate("make quiz", [table_chunk])
    _enterprise_note, enterprise_step = EnterpriseAgent().annotate("compliance policy?", [table_chunk])

    assert study_step.metadata["wants_quiz"] is True
    assert study_step.metadata["study_questions"]
    assert study_step.metadata["tables"] == 1
    assert "compliance" in enterprise_step.metadata["policy_terms"]
    assert enterprise_step.metadata["compliance_trail"][0]["document_id"] == "d2"
