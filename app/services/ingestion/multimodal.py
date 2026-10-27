from __future__ import annotations

import uuid
from pathlib import Path

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional visual dependency
    Image = None

try:
    import fitz
except Exception:  # pragma: no cover - optional PDF rendering dependency
    fitz = None


class MultimodalAssetExtractor:
    """Extract page previews and optional OCR evidence without requiring large models."""

    EXTRACTOR_VERSION = "multimodal-v1"
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}

    def __init__(self, preview_dir: str | Path | None = None, enable_ocr: bool = True) -> None:
        self.preview_dir = Path(preview_dir or "./data/previews")
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        self.enable_ocr = enable_ocr
        self._ocr_engine = None
        self._ocr_attempted = False
        self._last_ocr_confidence: float | None = None
        self._last_ocr_error: str | None = None

    def enrich_pdf_pages(self, file_path: str | Path, pages: list[dict]) -> list[dict]:
        assets = self.extract_page_assets(file_path)
        for page in pages:
            page_number = page["page_number"]
            page_assets = assets.get(page_number, {})
            metadata = {**page.get("metadata", {}), **page_assets}
            metadata.setdefault("visual_assets", [])
            metadata.setdefault("source_anchors", [])
            metadata["ocr_attempted"] = False
            metadata["ocr_available"] = False
            metadata["ocr_confidence"] = None
            metadata["is_scanned"] = not bool((page.get("text") or "").strip()) and bool(metadata.get("preview_path"))
            if not page.get("text") and metadata.get("preview_path"):
                preview_path = Path(metadata["preview_path"])
                metadata["ocr_attempted"] = self.enable_ocr
                ocr_text = self._extract_ocr_text(preview_path)
                metadata["ocr_available"] = bool(ocr_text)
                metadata["ocr_confidence"] = self._last_ocr_confidence
                metadata["ocr_error"] = self._last_ocr_error
                if ocr_text:
                    metadata["missing_evidence_notes"] = []
                elif self._last_ocr_error:
                    metadata["missing_evidence_notes"] = [f"OCR failed: {self._last_ocr_error}"]
                else:
                    metadata["missing_evidence_notes"] = ["OCR text is unavailable for this visual/scanned page."]
                if ocr_text and self._last_ocr_confidence is not None and self._last_ocr_confidence < 0.65:
                    metadata["missing_evidence_notes"] = ["OCR confidence is low; verify this evidence against the page preview."]
                page["text"] = ocr_text or f"Visual page {page_number} from {Path(file_path).name}."
            metadata = self._quality_metadata(metadata)
            page["metadata"] = metadata
        return pages

    def extract_page_assets(self, file_path: str | Path) -> dict[int, dict]:
        path = Path(file_path)
        if path.suffix.lower() != ".pdf" or fitz is None:
            return {}
        preview_root = self.preview_dir / path.stem
        preview_root.mkdir(parents=True, exist_ok=True)
        extracted: dict[int, dict] = {}
        try:
            document = fitz.open(str(path))
        except Exception:
            return {}
        try:
            for page_index in range(document.page_count):
                page_number = page_index + 1
                page = document.load_page(page_index)
                preview_path = preview_root / f"page-{page_number}.png"
                page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False).save(str(preview_path))
                image_count = len(page.get_images(full=True))
                asset_type = "image" if image_count else "page"
                anchor = self._visual_anchor(path.name, page_number, asset_type, preview_path)
                figure_anchors = self._page_image_anchors(page, path.name, page_number, preview_root, preview_path)
                anchors = figure_anchors or ([anchor] if image_count else [])
                extracted[page_number] = {
                    "has_images": image_count > 0,
                    "preview_path": str(preview_path),
                    "figures": anchors,
                    "visual_assets": anchors or [anchor],
                    "source_anchors": anchors or [anchor],
                    "layout_detected": True,
                    "text_blocks": self._page_text_blocks(page),
                }
        finally:
            document.close()
        return extracted

    def parse_image(self, file_path: str | Path) -> list[dict]:
        path = Path(file_path)
        text = self._extract_ocr_text(path) or f"Visual source from uploaded image {path.name}."
        width = None
        height = None
        if Image is not None:
            with Image.open(path) as image:
                width, height = image.size
        anchor = self._visual_anchor(path.name, 1, "image", path)
        return [
            {
                "page_number": 1,
                "text": text,
                "metadata": {
                    "page_width": width,
                    "page_height": height,
                    "has_images": True,
                    "tables": [],
                    "figures": [anchor],
                    "visual_assets": [anchor],
                    "source_anchors": [anchor],
                    "preview_path": str(path),
                    "ocr_available": bool(text),
                    "section_path": ["Uploaded Image"],
                    "visual_caption": text[:240] if text else f"Uploaded image {path.name}",
                    "ocr_attempted": self.enable_ocr,
                    "ocr_available": bool(text and not text.startswith("Visual source from uploaded image")),
                    "ocr_confidence": self._last_ocr_confidence,
                    "ocr_error": self._last_ocr_error,
                    "is_scanned": True,
                    "layout_detected": False,
                    "table_count": 0,
                    "chart_count": 0,
                    "figure_count": 1,
                    "crop_count": 1,
                },
            }
        ]

    def _extract_ocr_text(self, path: Path) -> str:
        self._last_ocr_confidence = None
        self._last_ocr_error = None
        if not self.enable_ocr:
            self._last_ocr_error = "OCR is disabled by configuration."
            return ""
        if not self._ocr_attempted:
            self._ocr_attempted = True
            try:
                from paddleocr import PaddleOCR

                self._ocr_engine = PaddleOCR(use_doc_orientation_classify=True, use_doc_unwarping=True, use_textline_orientation=True)
            except Exception as exc:
                self._last_ocr_error = f"PaddleOCR is unavailable: {exc}"
                self._ocr_engine = None
        if self._ocr_engine is None:
            self._last_ocr_error = self._last_ocr_error or "PaddleOCR engine is not initialized."
            return self._extract_tesseract_text(path)
        try:
            results = self._ocr_engine.predict(str(path))
        except Exception as exc:
            self._last_ocr_error = f"PaddleOCR prediction failed: {exc}"
            return ""
        texts: list[str] = []
        scores: list[float] = []
        for result in results or []:
            payload = getattr(result, "json", result)
            if callable(payload):
                payload = payload()
            if isinstance(payload, dict):
                rec_texts = payload.get("rec_texts") or payload.get("res", {}).get("rec_texts") or []
                texts.extend(str(text).strip() for text in rec_texts if str(text).strip())
                rec_scores = payload.get("rec_scores") or payload.get("res", {}).get("rec_scores") or []
                for score in rec_scores:
                    try:
                        scores.append(float(score))
                    except (TypeError, ValueError):
                        continue
        if scores:
            self._last_ocr_confidence = round(sum(scores) / len(scores), 4)
        if not texts:
            self._last_ocr_error = "PaddleOCR returned no recognized text."
            return self._extract_tesseract_text(path)
        return " ".join(texts)

    def _extract_tesseract_text(self, path: Path) -> str:
        if Image is None:
            self._last_ocr_error = f"{self._last_ocr_error or 'OCR unavailable'}; Pillow is unavailable for Tesseract fallback."
            return ""
        try:
            import pytesseract
        except Exception as exc:
            self._last_ocr_error = f"{self._last_ocr_error or 'PaddleOCR unavailable'}; Tesseract fallback is unavailable: {exc}"
            return ""
        try:
            with Image.open(path) as image:
                data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        except Exception as exc:
            self._last_ocr_error = f"{self._last_ocr_error or 'PaddleOCR failed'}; Tesseract fallback failed: {exc}"
            return ""
        texts: list[str] = []
        confidences: list[float] = []
        for text, conf in zip(data.get("text", []), data.get("conf", []), strict=False):
            cleaned = str(text).strip()
            if not cleaned:
                continue
            texts.append(cleaned)
            try:
                confidence = float(conf)
            except (TypeError, ValueError):
                continue
            if confidence >= 0:
                confidences.append(confidence / 100)
        if confidences:
            self._last_ocr_confidence = round(sum(confidences) / len(confidences), 4)
        if texts:
            self._last_ocr_error = None
            return " ".join(texts)
        self._last_ocr_error = f"{self._last_ocr_error or 'PaddleOCR failed'}; Tesseract returned no recognized text."
        return ""

    @staticmethod
    def _visual_anchor(filename: str, page_number: int, visual_type: str, preview_path: Path) -> dict:
        return {
            "anchor_id": str(uuid.uuid4()),
            "content_type": visual_type,
            "visual_type": visual_type,
            "filename": filename,
            "page_number": page_number,
            "preview_path": str(preview_path),
            "bbox": [0.0, 0.0, 1.0, 1.0],
            "crop_path": str(preview_path),
            "anchor_kind": "page_visual",
        }

    def _page_image_anchors(self, page, filename: str, page_number: int, preview_root: Path, preview_path: Path) -> list[dict]:
        if fitz is None:
            return []
        page_rect = page.rect
        anchors: list[dict] = []
        image_blocks = [block for block in page.get_text("dict").get("blocks", []) if block.get("type") == 1]
        for index, block in enumerate(image_blocks[:12], start=1):
            x0, y0, x1, y1 = [float(value) for value in block.get("bbox", page_rect)]
            bbox = [
                round(max(0.0, x0 / page_rect.width), 4),
                round(max(0.0, y0 / page_rect.height), 4),
                round(min(1.0, x1 / page_rect.width), 4),
                round(min(1.0, y1 / page_rect.height), 4),
            ]
            crop_path = preview_root / f"page-{page_number}-figure-{index}.png"
            try:
                page.get_pixmap(clip=fitz.Rect(x0, y0, x1, y1), matrix=fitz.Matrix(1.8, 1.8), alpha=False).save(str(crop_path))
            except Exception:
                crop_path = preview_path
            anchor = self._visual_anchor(filename, page_number, "figure", crop_path)
            anchor["bbox"] = bbox
            anchor["crop_path"] = str(crop_path)
            anchor["title"] = f"Figure {index} on page {page_number}"
            anchors.append(anchor)
        return anchors

    @staticmethod
    def _quality_metadata(metadata: dict) -> dict:
        figures = metadata.get("figures", []) or []
        visual_assets = metadata.get("visual_assets", []) or []
        metadata["table_count"] = len(metadata.get("tables", []) or [])
        metadata["chart_count"] = len(metadata.get("charts", []) or [])
        metadata["figure_count"] = len(figures)
        metadata["crop_count"] = sum(1 for item in visual_assets if item.get("crop_path"))
        metadata.setdefault("layout_detected", bool(metadata.get("text_blocks") or figures or visual_assets))
        return metadata

    @staticmethod
    def _page_text_blocks(page) -> list[dict]:
        if fitz is None:
            return []
        rect = page.rect
        blocks = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            x0, y0, x1, y1 = [float(value) for value in block.get("bbox", rect)]
            text = " ".join(
                span.get("text", "").strip()
                for line in block.get("lines", [])
                for span in line.get("spans", [])
                if span.get("text", "").strip()
            )
            if not text:
                continue
            blocks.append(
                {
                    "text": text[:500],
                    "bbox": [
                        round(max(0.0, x0 / rect.width), 4),
                        round(max(0.0, y0 / rect.height), 4),
                        round(min(1.0, x1 / rect.width), 4),
                        round(min(1.0, y1 / rect.height), 4),
                    ],
                }
            )
        return blocks[:50]
