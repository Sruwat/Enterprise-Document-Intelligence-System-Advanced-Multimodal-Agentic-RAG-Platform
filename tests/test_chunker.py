from app.services.ingestion.chunker import RecursiveChunker


def test_chunker_preserves_page_metadata():
    chunker = RecursiveChunker(chunk_size=20, chunk_overlap=5)
    pages = [{"page_number": 1, "text": "One two three four five six seven eight nine ten", "metadata": {"has_images": False}}]
    chunks = chunker.split_document("doc-1", "file.pdf", pages)
    assert len(chunks) >= 2
    assert all(chunk.page_number == 1 for chunk in chunks)
    assert all(chunk.metadata["page_number"] == 1 for chunk in chunks)


def test_chunker_creates_clause_level_chunks_with_legal_metadata():
    chunker = RecursiveChunker(chunk_size=80, chunk_overlap=10)
    pages = [
        {
            "page_number": 2,
            "text": "Termination: Either party may terminate with thirty days notice. Payment terms also apply.",
            "metadata": {
                "has_images": False,
                "clauses": [
                    {
                        "artifact_id": "clause-1",
                        "title": "Termination",
                        "text": "Either party may terminate with thirty days notice.",
                        "risk_tags": ["termination"],
                        "bbox": [0.1, 0.2, 0.9, 0.35],
                    }
                ],
                "legal_metadata": {"notice_period": "thirty days notice"},
                "source_anchors": [{"anchor_id": "clause-1", "content_type": "clause"}],
            },
        }
    ]

    chunks = chunker.split_document("doc-1", "contract.pdf", pages)

    clause_chunks = [chunk for chunk in chunks if chunk.content_type == "clause"]
    assert clause_chunks
    assert clause_chunks[0].section == "Termination"
    assert clause_chunks[0].metadata["legal_metadata"]["notice_period"] == "thirty days notice"
    assert clause_chunks[0].bbox == [0.1, 0.2, 0.9, 0.35]
