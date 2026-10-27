from __future__ import annotations

import csv
import io
from pathlib import Path
import re
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from app.services.ingestion.artifact_extractor import DocumentArtifactExtractor
from app.services.ingestion.multimodal import MultimodalAssetExtractor

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None


class PDFParser:
    PARSER_VERSION = "documentparser-v3"

    def __init__(self, asset_extractor: MultimodalAssetExtractor | None = None, artifact_extractor: DocumentArtifactExtractor | None = None) -> None:
        self.asset_extractor = asset_extractor or MultimodalAssetExtractor()
        self.artifact_extractor = artifact_extractor or DocumentArtifactExtractor()

    def parse(self, file_path: str | Path) -> list[dict]:
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix in self.asset_extractor.IMAGE_EXTENSIONS:
            return self.asset_extractor.parse_image(path)
        if suffix in {".txt", ".md"}:
            raw_text = path.read_text(encoding="utf-8", errors="ignore")
            normalized = self._normalize_extracted_text(raw_text)
            artifacts = self.artifact_extractor.extract(raw_text, normalized, 1)
            return [
                {
                    "page_number": 1,
                    "text": normalized,
                    "metadata": self._metadata_with_anchors(path.name, 1, artifacts, has_images=False),
                }
            ]
        if suffix == ".docx":
            return self._parse_docx(path)
        if suffix == ".csv":
            return self._parse_csv(path)
        if suffix == ".xlsx":
            return self._parse_xlsx(path)
        if suffix == ".pptx":
            return self._parse_pptx(path)
        if suffix != ".pdf":
            raise ValueError(f"Unsupported source type: {suffix or 'unknown'}")
        if PdfReader is None:
            raise RuntimeError("pypdf is required for PDF parsing.")
        reader = PdfReader(str(path))
        pages: list[dict] = []
        for index, page in enumerate(reader.pages, start=1):
            raw_text = page.extract_text() or ""
            text = self._normalize_extracted_text(raw_text)
            artifacts = self.artifact_extractor.extract(raw_text, text, index)
            pages.append(
                {
                    "page_number": index,
                    "text": text.strip(),
                    "metadata": {
                        **self._metadata_with_anchors(path.name, index, artifacts, has_images=bool(getattr(page, "images", []))),
                        "page_width": float(page.mediabox.width),
                        "page_height": float(page.mediabox.height),
                    },
                }
            )
        return self.asset_extractor.enrich_pdf_pages(path, pages)

    def _parse_docx(self, path: Path) -> list[dict]:
        raw_text, docx_tables = self._extract_docx_content(path)
        normalized = self._normalize_extracted_text(raw_text)
        artifacts = self.artifact_extractor.extract(raw_text, normalized, 1)
        metadata = self._metadata_with_anchors(path.name, 1, artifacts, has_images=False)
        if docx_tables and not metadata.get("tables"):
            metadata["tables"] = docx_tables
            metadata["table_json"] = docx_tables[0]
        return [
            {
                "page_number": 1,
                "text": normalized,
                "metadata": {
                    **metadata,
                    "source_type": ".docx",
                    "page_width": None,
                    "page_height": None,
                },
            }
        ]

    def _parse_csv(self, path: Path) -> list[dict]:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        rows = [row for row in csv.reader(io.StringIO(raw)) if any(cell.strip() for cell in row)]
        lines = [" | ".join(cell.strip() for cell in row) for row in rows]
        normalized = self._normalize_extracted_text("\n".join(lines))
        table = self._table_metadata("csv_table", rows, title=f"CSV table: {path.name}")
        artifacts = self.artifact_extractor.extract(raw, normalized, 1)
        metadata = self._metadata_with_anchors(path.name, 1, artifacts, has_images=False)
        if table:
            metadata["tables"] = [table, *metadata.get("tables", [])]
            metadata["table_json"] = table
            metadata["table_count"] = len(metadata["tables"])
        return [{"page_number": 1, "text": normalized, "metadata": {**metadata, "source_type": ".csv", "sheet_name": path.stem}}]

    def _parse_xlsx(self, path: Path) -> list[dict]:
        try:
            with ZipFile(path) as archive:
                shared_strings = self._xlsx_shared_strings(archive)
                workbook_sheets = self._xlsx_sheet_names(archive)
                worksheet_names = sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
                pages: list[dict] = []
                for index, worksheet_name in enumerate(worksheet_names, start=1):
                    rows = self._xlsx_rows(archive.read(worksheet_name), shared_strings)
                    lines = [" | ".join(row) for row in rows if any(cell for cell in row)]
                    text = self._normalize_extracted_text("\n".join(lines))
                    sheet_name = workbook_sheets.get(index, f"Sheet {index}")
                    artifacts = self.artifact_extractor.extract("\n".join(lines), text, index)
                    metadata = self._metadata_with_anchors(path.name, index, artifacts, has_images=False)
                    table = self._table_metadata("xlsx_sheet_xml", rows, title=sheet_name)
                    if table:
                        metadata["tables"] = [table, *metadata.get("tables", [])]
                        metadata["table_json"] = table
                        metadata["table_count"] = len(metadata["tables"])
                    pages.append({"page_number": index, "text": text, "metadata": {**metadata, "source_type": ".xlsx", "sheet_name": sheet_name}})
                return pages or [{"page_number": 1, "text": "", "metadata": {"source_type": ".xlsx", "sheet_name": "Workbook"}}]
        except (BadZipFile, KeyError, ElementTree.ParseError) as exc:
            raise ValueError("Uploaded file does not look like a valid XLSX workbook.") from exc

    def _parse_pptx(self, path: Path) -> list[dict]:
        try:
            with ZipFile(path) as archive:
                slide_names = sorted(name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
                pages = []
                for index, slide_name in enumerate(slide_names, start=1):
                    root = ElementTree.fromstring(archive.read(slide_name))
                    text_blocks = [node.text.strip() for node in root.iter() if node.tag.endswith("}t") and node.text and node.text.strip()]
                    raw = "\n".join(text_blocks)
                    text = self._normalize_extracted_text(raw)
                    artifacts = self.artifact_extractor.extract(raw, text, index)
                    metadata = self._metadata_with_anchors(path.name, index, artifacts, has_images=True)
                    pages.append({"page_number": index, "text": text, "metadata": {**metadata, "source_type": ".pptx", "slide_number": index}})
                return pages or [{"page_number": 1, "text": "", "metadata": {"source_type": ".pptx", "slide_number": 1}}]
        except (BadZipFile, KeyError, ElementTree.ParseError) as exc:
            raise ValueError("Uploaded file does not look like a valid PPTX deck.") from exc

    @staticmethod
    def _extract_docx_text(path: Path) -> str:
        text, _tables = PDFParser._extract_docx_content(path)
        return text

    @staticmethod
    def _extract_docx_content(path: Path) -> tuple[str, list[dict]]:
        try:
            with ZipFile(path) as archive:
                xml_bytes = archive.read("word/document.xml")
        except (BadZipFile, KeyError) as exc:
            raise ValueError("Uploaded file does not look like a valid DOCX document.") from exc

        root = ElementTree.fromstring(xml_bytes)
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        blocks: list[str] = []
        tables: list[dict] = []
        for element in root.iter():
            if element.tag == f"{{{namespace['w']}}}p":
                text = "".join(node.text or "" for node in element.findall(".//w:t", namespace)).strip()
                if text:
                    blocks.append(text)
            elif element.tag == f"{{{namespace['w']}}}tbl":
                rows = []
                for row in element.findall(".//w:tr", namespace):
                    cells = []
                    for cell in row.findall("./w:tc", namespace):
                        cell_text = " ".join(node.text or "" for node in cell.findall(".//w:t", namespace)).strip()
                        if cell_text:
                            cells.append(cell_text)
                    if cells:
                        rows.append(" | ".join(cells))
                if rows:
                    blocks.append("\n".join(rows))
                    headers = [cell.strip() for cell in rows[0].split("|")]
                    data_rows = [[cell.strip() for cell in row.split("|")] for row in rows[1:]]
                    tables.append(
                        {
                            "detected_by": "docx_table_xml",
                            "title": "Detected DOCX table",
                            "text": " | ".join(headers),
                            "headers": headers,
                            "rows": data_rows,
                            "row_count": len(data_rows),
                        }
                    )
        return "\n".join(blocks), tables

    @staticmethod
    def _table_metadata(detected_by: str, rows: list[list[str]], title: str) -> dict | None:
        clean_rows = [[cell.strip() for cell in row] for row in rows if any(cell.strip() for cell in row)]
        if not clean_rows:
            return None
        headers = clean_rows[0]
        data_rows = clean_rows[1:]
        return {
            "detected_by": detected_by,
            "title": title,
            "text": " | ".join(headers),
            "headers": headers,
            "rows": data_rows,
            "row_count": len(data_rows),
        }

    @staticmethod
    def _xlsx_shared_strings(archive: ZipFile) -> list[str]:
        try:
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        except KeyError:
            return []
        strings = []
        for item in root:
            strings.append("".join(node.text or "" for node in item.iter() if node.tag.endswith("}t")).strip())
        return strings

    @staticmethod
    def _xlsx_sheet_names(archive: ZipFile) -> dict[int, str]:
        try:
            root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        except KeyError:
            return {}
        names: dict[int, str] = {}
        for index, sheet in enumerate([node for node in root.iter() if node.tag.endswith("}sheet")], start=1):
            names[index] = sheet.attrib.get("name", f"Sheet {index}")
        return names

    @staticmethod
    def _xlsx_rows(xml_bytes: bytes, shared_strings: list[str]) -> list[list[str]]:
        root = ElementTree.fromstring(xml_bytes)
        rows: list[list[str]] = []
        for row in [node for node in root.iter() if node.tag.endswith("}row")]:
            cells: list[str] = []
            for cell in [node for node in row if node.tag.endswith("}c")]:
                value_node = next((node for node in cell if node.tag.endswith("}v")), None)
                inline_node = next((node for node in cell.iter() if node.tag.endswith("}t")), None)
                value = value_node.text if value_node is not None and value_node.text is not None else inline_node.text if inline_node is not None else ""
                if cell.attrib.get("t") == "s":
                    try:
                        value = shared_strings[int(value)]
                    except (ValueError, IndexError):
                        pass
                cells.append(str(value).strip())
            if cells:
                rows.append(cells)
        return rows

    @classmethod
    def _normalize_extracted_text(cls, text: str) -> str:
        text = text.replace("\x00", " ")
        text = re.sub(r"(?:(?<=\b)[A-Za-z0-9]\s+){2,}[A-Za-z0-9](?=\b)", lambda match: match.group(0).replace(" ", ""), text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _metadata_from_artifacts(artifacts, has_images: bool) -> dict:
        first_table = artifacts.tables[0] if artifacts.tables else None
        first_chart = artifacts.charts[0] if artifacts.charts else None
        return {
            "has_images": has_images,
            "tables": artifacts.tables,
            "charts": artifacts.charts,
            "figures": [],
            "clauses": artifacts.clauses,
            "risks": artifacts.risks,
            "definitions": artifacts.definitions,
            "legal_metadata": artifacts.legal_metadata,
            "visual_assets": [],
            "source_anchors": [],
            "section_path": artifacts.section_path,
            "table_json": first_table,
            "chart_series": first_chart,
            "risk_tags": sorted({risk.get("tag") for risk in artifacts.risks if risk.get("tag")}),
            "table_count": len(artifacts.tables),
            "chart_count": len(artifacts.charts),
            "figure_count": 0,
            "crop_count": 0,
            "layout_detected": bool(artifacts.section_path or artifacts.tables or artifacts.charts or artifacts.clauses),
            "ocr_attempted": False,
            "ocr_available": False,
            "ocr_confidence": None,
            "is_scanned": False,
        }

    @classmethod
    def _metadata_with_anchors(cls, filename: str, page_number: int, artifacts, has_images: bool) -> dict:
        metadata = cls._metadata_from_artifacts(artifacts, has_images=has_images)
        anchors = cls._artifact_anchors(filename, page_number, artifacts)
        metadata["source_anchors"] = [*metadata.get("source_anchors", []), *anchors]
        metadata["visual_assets"] = [*metadata.get("visual_assets", []), *[anchor for anchor in anchors if anchor["content_type"] in {"table", "chart", "figure"}]]
        return metadata

    @staticmethod
    def _artifact_anchors(filename: str, page_number: int, artifacts) -> list[dict]:
        anchors: list[dict] = []
        for artifact_type, items in (
            ("table", artifacts.tables),
            ("chart", artifacts.charts),
            ("clause", artifacts.clauses),
            ("risk", artifacts.risks),
            ("definition", artifacts.definitions),
        ):
            for item in items:
                anchors.append(
                    {
                        "anchor_id": item.get("artifact_id"),
                        "anchor_kind": "extracted_artifact",
                        "content_type": artifact_type,
                        "visual_type": artifact_type,
                        "filename": filename,
                        "page_number": page_number,
                        "preview_path": item.get("preview_path"),
                        "crop_path": item.get("crop_path"),
                        "bbox": item.get("bbox") or [0.0, 0.0, 1.0, 1.0],
                        "title": item.get("title"),
                    }
                )
        return anchors
