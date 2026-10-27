from zipfile import ZIP_DEFLATED, ZipFile

from app.services.ingestion.parser import PDFParser


def test_parser_normalizes_fragmented_pdf_text():
    raw = "T h i s   i s   a   p r o p o s a l   f o r   O r r a"
    normalized = PDFParser._normalize_extracted_text(raw)
    assert "This" in normalized
    assert "proposal" in normalized
    assert "Orra" in normalized


def test_parser_extracts_docx_contract_text_and_tables(tmp_path):
    docx_path = tmp_path / "contract.docx"
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>1 Payment Terms</w:t></w:r></w:p>
        <w:p><w:r><w:t>Payment: Customer shall pay invoices within 30 days and late payment may trigger penalty fees.</w:t></w:r></w:p>
        <w:tbl>
          <w:tr><w:tc><w:p><w:r><w:t>Clause</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Owner</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr><w:tc><w:p><w:r><w:t>Payment</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Buyer</w:t></w:r></w:p></w:tc></w:tr>
        </w:tbl>
      </w:body>
    </w:document>
    """
    with ZipFile(docx_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)

    pages = PDFParser().parse(docx_path)

    assert len(pages) == 1
    assert "Payment Terms" in pages[0]["text"]
    assert pages[0]["metadata"]["source_type"] == ".docx"
    assert pages[0]["metadata"]["tables"]
    assert "payment" in pages[0]["metadata"]["risk_tags"]


def test_parser_extracts_csv_table_metadata(tmp_path):
    csv_path = tmp_path / "metrics.csv"
    csv_path.write_text("Quarter,Revenue,Risk\nQ1,100,Low\nQ2,140,Medium\n", encoding="utf-8")

    pages = PDFParser().parse(csv_path)

    assert len(pages) == 1
    assert "Quarter" in pages[0]["text"]
    assert pages[0]["metadata"]["source_type"] == ".csv"
    assert pages[0]["metadata"]["table_json"]["headers"] == ["Quarter", "Revenue", "Risk"]
    assert pages[0]["metadata"]["table_json"]["row_count"] == 2


def test_parser_extracts_xlsx_sheets_and_tables(tmp_path):
    xlsx_path = tmp_path / "workbook.xlsx"
    workbook_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <sheets><sheet name="Risks" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets>
    </workbook>
    """
    shared_strings_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <si><t>Item</t></si><si><t>Status</t></si><si><t>OCR</t></si><si><t>Needs review</t></si>
    </sst>
    """
    sheet_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <sheetData>
        <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
        <row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2" t="s"><v>3</v></c></row>
      </sheetData>
    </worksheet>
    """
    with ZipFile(xlsx_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/sharedStrings.xml", shared_strings_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)

    pages = PDFParser().parse(xlsx_path)

    assert len(pages) == 1
    assert pages[0]["metadata"]["source_type"] == ".xlsx"
    assert pages[0]["metadata"]["sheet_name"] == "Risks"
    assert pages[0]["metadata"]["table_json"]["headers"] == ["Item", "Status"]
    assert "Needs review" in pages[0]["text"]


def test_parser_extracts_pptx_slide_text(tmp_path):
    pptx_path = tmp_path / "deck.pptx"
    slide_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
           xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
      <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Enterprise RAG Roadmap</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
    </p:sld>
    """
    with ZipFile(pptx_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("ppt/slides/slide1.xml", slide_xml)

    pages = PDFParser().parse(pptx_path)

    assert len(pages) == 1
    assert pages[0]["metadata"]["source_type"] == ".pptx"
    assert pages[0]["metadata"]["slide_number"] == 1
    assert "Enterprise RAG Roadmap" in pages[0]["text"]
