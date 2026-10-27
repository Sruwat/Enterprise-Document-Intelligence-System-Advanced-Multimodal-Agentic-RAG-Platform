"""Measure real parse/chunk/preview timings for long-document fixtures."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.services.ingestion.chunker import RecursiveChunker
from app.services.ingestion.parser import PDFParser


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", nargs="?", default="data/validation_latency/aiwana_200_page_multimodal_benchmark.pdf")
    parser.add_argument("--output", default="data/benchmarks/long_document.json")
    args = parser.parse_args()
    source = Path(args.pdf)
    if not source.exists():
        print(json.dumps({"status": "missing_fixture", "path": str(source)}))
        return 2
    settings = Settings(DATA_DIR="data/benchmarks/runtime", ENABLE_MULTIMODAL=False)
    parser_service = PDFParser()
    chunker = RecursiveChunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    started = time.perf_counter()
    parsed = parser_service.parse(source)
    parse_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    chunks = chunker.split_document("benchmark", source.name, parsed)
    chunk_ms = (time.perf_counter() - started) * 1000
    payload = {"status": "ok", "path": str(source), "pages": len(parsed), "chunks": len(chunks), "parse_ms": round(parse_ms, 2), "chunk_ms": round(chunk_ms, 2), "ocr": "disabled", "note": "Embedding, Qdrant, graph, and OCR timings require a live configured stack and are not inferred here."}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
