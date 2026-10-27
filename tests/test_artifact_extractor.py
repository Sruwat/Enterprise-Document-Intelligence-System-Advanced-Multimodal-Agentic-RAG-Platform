from app.core.schemas import Citation, ChunkRecord
from app.core.schemas import EvidenceAnchorRecord
from app.services.agents.evidence_agent import EvidenceAgent
from app.services.ingestion.artifact_extractor import DocumentArtifactExtractor
from app.services.ingestion.parser import PDFParser
from app.storage.metadata_store import MetadataStore
from datetime import datetime


def test_artifact_extractor_detects_contract_risks_tables_and_charts():
    raw = """
    4 Termination
    Termination: Either party may terminate immediately for material breach and unpaid payment obligations.

    Quarter | Revenue | Cost
    Q1 | 120 | 80
    Q2 | 150 | 90

    The chart shows Q1 120 and Q2 150 with an increasing trend.
    "Confidential Information" means all non-public business information.
    """
    normalized = PDFParser._normalize_extracted_text(raw)
    artifacts = DocumentArtifactExtractor().extract(raw, normalized, 4)

    assert artifacts.section_path == ["4 Termination"]
    assert artifacts.tables and artifacts.tables[0]["headers"] == ["Quarter", "Revenue", "Cost"]
    assert artifacts.charts and artifacts.charts[0]["point_count"] >= 2
    assert artifacts.clauses and "Termination" in artifacts.clauses[0]["title"]
    assert {risk["tag"] for risk in artifacts.risks} >= {"termination", "breach", "payment"}
    assert artifacts.definitions and artifacts.definitions[0]["title"] == "Confidential Information"


def test_artifact_extractor_extracts_legal_metadata():
    raw = """
    Services Agreement by and between Acme Corp and Beta LLC.
    Effective Date: January 1, 2026.
    Payment Terms: invoices are due within 30 days.
    Governing Law: Delaware.
    The vendor shall provide support within 5 days after notice.
    Either party may terminate with 30 days notice.
    Late payment penalty is 2 percent per month.
    """
    normalized = PDFParser._normalize_extracted_text(raw)
    artifacts = DocumentArtifactExtractor().extract(raw, normalized, 1)

    legal = artifacts.legal_metadata
    assert "Acme Corp" in legal["parties"]
    assert legal["effective_date"] == "January 1, 2026"
    assert legal["governing_law"] == "Delaware"
    assert "notice" in legal["notice_period"]
    assert legal["obligations"]
    assert legal["penalties"]


def test_parser_metadata_from_artifacts_marks_structured_content():
    raw = "Payment: Fees are due in 30 days. Quarter | Revenue\nQ1 | 100\nQ2 | 120\nThe chart shows Q1 100 and Q2 120."
    normalized = PDFParser._normalize_extracted_text(raw)
    artifacts = DocumentArtifactExtractor().extract(raw, normalized, 1)
    metadata = PDFParser._metadata_from_artifacts(artifacts, has_images=False)

    assert metadata["tables"]
    assert metadata["chart_series"]
    assert "payment" in metadata["risk_tags"]
    assert "legal_metadata" in metadata


def test_parser_metadata_adds_artifact_source_anchors():
    raw = "Payment: Fees are due in 30 days. Quarter | Revenue\nQ1 | 100\nQ2 | 120\nThe chart shows Q1 100 and Q2 120."
    normalized = PDFParser._normalize_extracted_text(raw)
    artifacts = DocumentArtifactExtractor().extract(raw, normalized, 1)
    metadata = PDFParser._metadata_with_anchors("report.pdf", 1, artifacts, has_images=False)

    assert metadata["source_anchors"]
    assert any(anchor["content_type"] == "table" for anchor in metadata["source_anchors"])
    assert all(len(anchor["bbox"]) == 4 for anchor in metadata["source_anchors"])
    assert any(anchor["bbox"] != [0.0, 0.0, 1.0, 1.0] for anchor in metadata["source_anchors"])


def test_artifact_extractor_adds_real_anchor_bboxes():
    raw = """
    Project Summary
    Quarter | Revenue | Cost
    Q1 | 120 | 80
    Q2 | 150 | 90
    The chart shows Q1 120 and Q2 150 with an increasing trend.
    """
    normalized = PDFParser._normalize_extracted_text(raw)
    artifacts = DocumentArtifactExtractor().extract(raw, normalized, 2)

    assert artifacts.tables[0]["bbox"] != [0.0, 0.0, 1.0, 1.0]
    assert artifacts.charts[0]["bbox"][3] <= 1.0


def test_evidence_canvas_surfaces_artifact_cards():
    chunk = ChunkRecord(
        chunk_id="chunk-1",
        document_id="doc-1",
        filename="contract.pdf",
        page_number=4,
        text="Termination may happen after material breach.",
        metadata={
            "page_metadata": {
                "clauses": [{"artifact_id": "clause-1", "title": "Termination", "text": "Either party may terminate for breach.", "risk_tags": ["termination", "breach"]}],
                "risks": [{"artifact_id": "risk-1", "title": "Breach", "text": "Material breach permits termination.", "tag": "breach", "severity": "high"}],
            }
        },
    )
    citation = Citation(document_id="doc-1", filename="contract.pdf", page_number=4, chunk_id="chunk-1", snippet=chunk.text)
    canvas, _ = EvidenceAgent().build_canvas(
        chunks=[chunk],
        citations=[citation],
        confidence=0.8,
        route_used="analytical",
        include_visual=False,
        answer_preview="Termination risk exists.",
    )

    assert {card["artifact_type"] for card in canvas.artifact_cards} == {"clause", "risk"}
    assert any(card["severity"] == "high" for card in canvas.artifact_cards)


def test_metadata_store_persists_evidence_anchors(tmp_path):
    store = MetadataStore(tmp_path / "metadata.db")
    anchor = EvidenceAnchorRecord(
        anchor_id="anchor-1",
        document_id="doc-1",
        workspace_id="default",
        chunk_id="chunk-1",
        anchor_type="chunk",
        page_number=2,
        bbox=[0.1, 0.2, 0.8, 0.9],
        preview_path="page-2.png",
        crop_path=None,
        citation_text="Grounded citation text.",
        created_at=datetime.utcnow(),
    )

    store.upsert_evidence_anchor(anchor)

    loaded = store.get_evidence_anchor("anchor-1")
    assert loaded is not None
    assert loaded.bbox == [0.1, 0.2, 0.8, 0.9]
    assert store.list_evidence_anchors(document_id="doc-1")[0].citation_text == "Grounded citation text."
