from pathlib import Path

from app.core.schemas import ChunkRecord
from app.services.agents.evidence_agent import EvidenceAgent
from app.services.ingestion.multimodal import MultimodalAssetExtractor
from app.services.ingestion.parser import PDFParser


def test_parser_adds_extraction_quality_metadata_for_structured_text():
    raw = "Results\nQuarter | Revenue\nQ1 | 10\nQ2 | 12\nThe chart peaked in Q2: 12 percent."
    artifacts = PDFParser().artifact_extractor.extract(raw, PDFParser._normalize_extracted_text(raw), 1)
    metadata = PDFParser._metadata_from_artifacts(artifacts, has_images=False)

    assert metadata["table_count"] == 1
    assert metadata["chart_count"] == 1
    assert metadata["layout_detected"] is True


def test_visual_page_without_ocr_records_missing_evidence_note(tmp_path):
    preview = tmp_path / "page.png"
    preview.write_bytes(b"not-a-real-image")
    extractor = MultimodalAssetExtractor(tmp_path, enable_ocr=False)
    pages = [{"page_number": 1, "text": "", "metadata": {"preview_path": str(preview), "has_images": True}}]

    enriched = extractor.enrich_pdf_pages(tmp_path / "scan.pdf", pages)

    metadata = enriched[0]["metadata"]
    assert metadata["ocr_attempted"] is False
    assert metadata["ocr_available"] is False
    assert "OCR failed" in metadata["missing_evidence_notes"][0]
    assert metadata["ocr_error"] == "OCR is disabled by configuration."
    assert metadata["is_scanned"] is True


def test_visual_page_records_low_ocr_confidence_note(tmp_path):
    preview = tmp_path / "page.png"
    preview.write_bytes(b"not-a-real-image")
    extractor = MultimodalAssetExtractor(tmp_path, enable_ocr=True)
    extractor._extract_ocr_text = lambda _path: "Low confidence OCR text"  # type: ignore[method-assign]
    extractor._last_ocr_confidence = 0.5
    pages = [{"page_number": 1, "text": "", "metadata": {"preview_path": str(preview), "has_images": True}}]

    enriched = extractor.enrich_pdf_pages(tmp_path / "scan.pdf", pages)

    metadata = enriched[0]["metadata"]
    assert metadata["ocr_available"] is True
    assert metadata["ocr_confidence"] == 0.5
    assert "OCR confidence is low" in metadata["missing_evidence_notes"][0]


def test_evidence_canvas_surfaces_missing_ocr_note():
    chunk = ChunkRecord(
        chunk_id="c1",
        document_id="d1",
        filename="scan.pdf",
        page_number=1,
        text="Visual page 1 from scan.pdf.",
        token_count=5,
        metadata={"page_metadata": {"missing_evidence_notes": ["OCR text is unavailable for this visual/scanned page."]}},
    )

    canvas, _step = EvidenceAgent().build_canvas(
        chunks=[chunk],
        citations=[],
        confidence=0.2,
        route_used="visual_question",
        include_visual=True,
    )

    assert any("OCR text is unavailable" in note for note in canvas.missing_evidence)
