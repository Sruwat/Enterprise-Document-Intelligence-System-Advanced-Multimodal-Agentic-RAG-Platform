from app.storage.bm25_store import BM25IndexStore


def test_bm25_returns_relevant_document_first():
    store = BM25IndexStore()
    store.upsert_documents(
        {
            "a": "revenue increased strongly in the quarter",
            "b": "this document is about compliance processes",
        }
    )
    results = store.search("revenue quarter", top_k=2)
    assert results[0][0] == "a"
