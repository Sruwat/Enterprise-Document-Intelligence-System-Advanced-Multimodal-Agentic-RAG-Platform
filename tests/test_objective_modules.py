from app.core.schemas import ChunkRecord
from app.services.agents.objective_agents import EnterpriseAgent, LegalAgent, StudyAgent


def test_legal_agent_returns_clause_inventory_and_timeline():
    chunk = ChunkRecord(
        chunk_id="c1",
        document_id="d1",
        filename="contract.pdf",
        page_number=2,
        text="Payment: Vendor shall invoice within 30 days. Termination applies after breach.",
        token_count=10,
        metadata={"page_metadata": {"clauses": [{"title": "Payment", "text": "Vendor shall invoice within 30 days.", "risk_tags": ["payment"]}]}},
    )

    _note, step = LegalAgent().annotate("Find obligations", [chunk])

    assert step.metadata["clause_inventory"][0]["title"] == "Payment"
    assert step.metadata["obligation_timeline"][0]["due"] == "30 days"


def test_study_agent_returns_deep_summary_and_table_chart_explanations():
    chunk = ChunkRecord(
        chunk_id="c1",
        document_id="d1",
        filename="study.pdf",
        page_number=3,
        text="Quarterly revenue increased.",
        token_count=3,
        table_json={"title": "Revenue table"},
        chart_series={"title": "Revenue trend"},
    )

    _note, step = StudyAgent().annotate("quiz me on the chart", [chunk])

    assert step.metadata["deep_summary"]
    assert {item["type"] for item in step.metadata["table_chart_explanations"]} == {"table", "chart"}
    assert step.metadata["study_questions"]


def test_enterprise_agent_returns_policy_answer_packet():
    chunk = ChunkRecord(
        chunk_id="c1",
        document_id="policy-1",
        filename="policy.pdf",
        page_number=1,
        text="The security policy requires approval and audit evidence.",
        token_count=8,
    )

    _note, step = EnterpriseAgent().annotate("What does the security policy require?", [chunk])

    packet = step.metadata["policy_answer_packet"]
    assert packet["source_document_ids"] == ["policy-1"]
    assert "approval_caveat" in packet
    assert {"security", "policy", "approval", "audit"} <= set(packet["policy_terms"])
