from pathlib import Path

from app.services.ingestion.indexer import DocumentIndexer
from app.storage.bm25_store import BM25IndexStore
from app.storage.metadata_store import MetadataStore


class FakeParser:
    def __init__(self):
        self.calls = 0

    def parse(self, _path):
        self.calls += 1
        return [
            {
                "page_number": 1,
                "text": "Revenue increased by 20 percent in 2025.",
                "metadata": {"has_images": False, "tables": [], "figures": []},
            }
        ]


class FakeChunker:
    def split_document(self, document_id, filename, pages):
        from app.core.schemas import ChunkRecord

        return [
            ChunkRecord(
                chunk_id=f"{document_id}-chunk-1",
                document_id=document_id,
                filename=filename,
                page_number=1,
                text=pages[0]["text"],
                token_count=6,
                metadata={"page_number": 1},
            )
        ]


class FakeEmbedder:
    def embed_documents(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeVectorStore:
    def __init__(self):
        self.points = {}

    def upsert(self, ids, vectors, payloads, sparse_vectors=None):
        for point_id, vector, payload in zip(ids, vectors, payloads):
            self.points[point_id] = {"vector": vector, "payload": payload, "sparse": (sparse_vectors or [])}

    def delete(self, ids):
        for point_id in ids:
            self.points.pop(point_id, None)


def test_duplicate_ingestion_reuses_existing_document(tmp_path):
    db_path = tmp_path / "metadata.db"
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"fake-pdf-content")

    metadata_store = MetadataStore(db_path)
    vector_store = FakeVectorStore()
    sparse_store = BM25IndexStore()
    indexer = DocumentIndexer(
        parser=FakeParser(),
        chunker=FakeChunker(),
        embedder=FakeEmbedder(),
        vector_store=vector_store,
        sparse_store=sparse_store,
        metadata_store=metadata_store,
    )

    first = indexer.ingest_pdf(pdf_path)
    second = indexer.ingest_pdf(pdf_path)

    assert first.document.status == "indexed"
    assert second.duplicate is True
    assert first.document.document_id == second.document.document_id
    assert len(metadata_store.list_documents()) == 1
    assert metadata_store.chunk_count() == 1


def test_force_reindex_rebuilds_existing_document(tmp_path):
    db_path = tmp_path / "metadata.db"
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"fake-pdf-content")

    metadata_store = MetadataStore(db_path)
    parser = FakeParser()
    vector_store = FakeVectorStore()
    sparse_store = BM25IndexStore()
    indexer = DocumentIndexer(
        parser=parser,
        chunker=FakeChunker(),
        embedder=FakeEmbedder(),
        vector_store=vector_store,
        sparse_store=sparse_store,
        metadata_store=metadata_store,
    )

    first = indexer.ingest_pdf(pdf_path)
    second = indexer.ingest_pdf(pdf_path, force_reindex=True)

    assert first.document.document_id == second.document.document_id
    assert second.duplicate is False
    assert parser.calls == 2
    assert len(metadata_store.list_documents()) == 1
    assert metadata_store.chunk_count() == 1
