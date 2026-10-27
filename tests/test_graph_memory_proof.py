from app.services.graph_memory import GraphExtractor, PostgresGraphRepository


def test_graph_extractor_creates_entities_and_relationships():
    extractor = GraphExtractor()
    result = extractor.extract_document(
        filename="NovaTech contract.pdf",
        pages=[
            {
                "page_number": 3,
                "text": "NovaTech shall provide thirty days notice before termination. The termination clause creates notice obligation risk.",
                "metadata": {"source_anchors": [{"anchor_id": "anchor-1"}]},
            }
        ],
    )

    assert result["entities"]
    assert any(rel["source_name"] == "NovaTech" for rel in result["relationships"])
    assert any(rel["relationship_type"] == "CREATES_OBLIGATION" for rel in result["relationships"])


def test_graph_repository_indexes_retrieves_and_proves_lift(tmp_path):
    repo = PostgresGraphRepository(f"sqlite:///{tmp_path / 'graph.db'}")
    indexed = repo.index_document_graph(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        document_id="doc-1",
        filename="NovaTech contract.pdf",
        pages=[
            {
                "page_number": 3,
                "text": "NovaTech shall provide thirty days notice before termination. The termination clause creates notice obligation risk.",
                "metadata": {"source_anchors": [{"anchor_id": "anchor-1"}]},
            }
        ],
    )

    facts = repo.search_graph("NovaTech termination obligation", tenant_id="tenant-a", workspace_id="workspace-a")

    assert indexed["entities"] >= 2
    assert indexed["relationships"] >= 1
    assert facts
    assert any(fact.relationship and fact.relationship.relationship_type == "CREATES_OBLIGATION" for fact in facts)
    assert any(fact.document_id == "doc-1" and fact.page_number == 3 for fact in facts)
