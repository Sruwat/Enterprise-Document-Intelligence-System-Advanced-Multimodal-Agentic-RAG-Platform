from app.storage.qdrant import QdrantVectorStore


def test_qdrant_point_vector_includes_optional_sparse_vector():
    store = QdrantVectorStore(":memory:", "test_sparse", use_named_vectors=True, use_sparse_vectors=True)

    vector = store._point_vector([0.1, 0.2], {7: 0.4, 9: 0.8})

    assert "text_dense" in vector
    assert "text_sparse" in vector
    assert vector["text_sparse"].indices == [7, 9]
    assert vector["text_sparse"].values == [0.4, 0.8]


def test_qdrant_point_vector_routes_table_and_visual_vectors():
    store = QdrantVectorStore(":memory:", "test_named", use_named_vectors=True, use_sparse_vectors=False)

    table_vector = store._point_vector([0.1, 0.2], payload={"content_type": "table"})
    visual_vector = store._point_vector([0.1, 0.2], payload={"content_type": "visual_text"})

    assert set(table_vector) == {"text_dense", "table_dense"}
    assert set(visual_vector) == {"text_dense", "visual_dense"}


def test_qdrant_collection_report_flags_missing_schema_without_client():
    store = QdrantVectorStore(":memory:", "test_report", use_named_vectors=True, use_sparse_vectors=True)
    store.client = None

    report = store.verify_collection(1024)

    assert report["available"] is False
    assert report["missing_named_vectors"] == ["table_dense", "text_dense", "visual_dense"]
    assert report["missing_sparse_vectors"] == ["text_sparse"]


def test_dense_retrieval_merges_sparse_results_without_duplicates():
    from app.services.retrieval.dense import DenseRetriever

    dense = [{"id": "a", "score": 0.9}, {"id": "b", "score": 0.8}]
    sparse = [{"id": "b", "score": 1.0}, {"id": "c", "score": 0.7}]

    merged = DenseRetriever._merge_results(dense, sparse)

    assert [item["id"] for item in merged] == ["a", "b", "c"]
    assert len({item["id"] for item in merged}) == 3
