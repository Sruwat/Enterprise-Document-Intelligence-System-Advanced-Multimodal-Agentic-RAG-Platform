from datetime import datetime

from app.core.config import Settings
from app.core.schemas import DocumentRecord
from app.core import dependencies
from app.db.repositories.postgres_metadata import PostgresMetadataRepository
from app.services.agents.retrieval_agent import RetrievalAgent
from app.services.graph_memory import DisabledGraphRepository, PostgresGraphRepository


def test_graph_repository_indexes_document_entities_and_relationships(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'graph.db'}"
    metadata = PostgresMetadataRepository(database_url)
    user = metadata.create_user("graph@example.com", tenant_id="tenant-graph")
    workspace = metadata.create_workspace("Graph Workspace", owner_id=user.user_id, tenant_id=user.tenant_id)
    metadata.upsert_document(
        DocumentRecord(
            document_id="doc-graph",
            workspace_id=workspace.workspace_id,
            filename="contract.pdf",
            source_path=str(tmp_path / "contract.pdf"),
            fingerprint="fp-graph",
            status="indexed",
            page_count=1,
            ingested_at=datetime.utcnow(),
        )
    )
    graph = PostgresGraphRepository(database_url)
    pages = [
        {
            "page_number": 1,
            "text": "NovaTech LLC shall provide notice within 30 days. Termination carries operational risk.",
            "metadata": {
                "clauses": [
                    {
                        "artifact_id": "clause-1",
                        "title": "Termination",
                        "text": "NovaTech LLC shall provide notice within 30 days.",
                    }
                ],
                "risks": [
                    {
                        "artifact_id": "risk-1",
                        "title": "Operational Risk",
                        "text": "Termination carries operational risk.",
                    }
                ],
            },
        }
    ]

    result = graph.index_document_graph(
        tenant_id=workspace.tenant_id,
        workspace_id=workspace.workspace_id,
        document_id="doc-graph",
        filename="contract.pdf",
        pages=pages,
    )
    facts = graph.search_graph("Termination operational risk", tenant_id=workspace.tenant_id, workspace_id=workspace.workspace_id)

    assert result["entities"] >= 4
    assert result["relationships"] >= 2
    assert any(fact.source.canonical_name == "Termination" and fact.evidence_anchor_id == "clause-1" for fact in facts)
    assert any(fact.relationship and fact.relationship.relationship_type in {"CONTAINS_CLAUSE", "HAS_RISK"} for fact in facts)


def test_graph_repository_dependency_is_disabled_until_postgres_graph_enabled(monkeypatch, tmp_path):
    dependencies.get_graph_repository.cache_clear()
    settings = Settings(
        ENABLE_GRAPH_MEMORY=True,
        DATABASE_BACKEND="sqlite",
        DATABASE_URL=f"sqlite:///{tmp_path / 'graph.db'}",
        DATA_DIR=str(tmp_path),
        UPLOAD_DIR=str(tmp_path / "uploads"),
        LOG_DIR=str(tmp_path / "logs"),
        METADATA_DB=str(tmp_path / "metadata.db"),
    )
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)

    assert isinstance(dependencies.get_graph_repository(), DisabledGraphRepository)
    dependencies.get_graph_repository.cache_clear()


def test_retrieval_agent_plans_graph_search_for_agentic_objective_modes():
    plan, step = RetrievalAgent().plan(
        route_used="analytical",
        objective_profile="legal",
        analysis_mode="agentic",
        requested_top_k=5,
        has_visual_request=False,
        context={"document_memories": [{"metadata": {}}]},
    )

    tool_names = {tool["tool_name"] for tool in plan["agent_decision"]["tools"]}
    assert plan["use_graph"] is True
    assert "search_graph" in tool_names
    assert step.metadata["use_graph"] is True
