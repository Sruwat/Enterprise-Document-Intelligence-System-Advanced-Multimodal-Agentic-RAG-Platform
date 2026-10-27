from __future__ import annotations

import argparse
from pathlib import Path


def generate_large_pdf(path: Path, pages: int = 120) -> None:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    for page in range(1, pages + 1):
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(72, height - 72, f"Aiwana Large Document Validation Page {page}")
        pdf.setFont("Helvetica", 11)
        pdf.drawString(72, height - 110, f"This synthetic page validates 100+ page parsing, chunking, embeddings, and citations. Page={page}.")
        pdf.drawString(72, height - 136, "Expected behavior: queue-first ingestion must not time out the upload request.")
        pdf.showPage()
    pdf.save()


def generate_scanned_like_pdf(path: Path) -> None:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(72, height - 90, "Aiwana OCR Validation")
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, height - 130, "This fixture is text-backed but reserved for scanned-PDF OCR pipeline checks.")
    pdf.drawString(72, height - 156, "OCR status must report confidence, failed pages, engine, and retry metadata.")
    pdf.save()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Aiwana ingestion validation fixtures.")
    parser.add_argument("--out", default="data/validation_corpus", help="Output directory.")
    parser.add_argument("--pages", type=int, default=120, help="Number of pages for the large PDF fixture.")
    args = parser.parse_args()
    out = Path(args.out)
    generate_large_pdf(out / "aiwana_120_page_validation.pdf", pages=args.pages)
    generate_scanned_like_pdf(out / "aiwana_scanned_ocr_validation.pdf")
    print(f"Generated validation corpus in {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
