from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

from fastapi.testclient import TestClient
from datasets import Dataset
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from ragas import evaluate
from ragas.dataset_schema import EvaluationResult
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import Faithfulness, LLMContextPrecisionWithoutReference, ResponseRelevancy

from app.api.main import app
from app.core.config import get_settings


DEFAULT_DATASET = Path("data/eval_dataset_novatech.json")
DEFAULT_OUTPUT = Path("data/evaluation_results.json")
DEFAULT_DOCUMENT_CANDIDATES = [
    Path(r"C:\Users\shank\Downloads\NovaTech_RAG_Test_Report.pdf"),
    Path("data/sample_report.pdf"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RAGAS evaluation against the existing RAG query pipeline.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Path to evaluation dataset JSON file.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Path to save evaluation results JSON.")
    parser.add_argument("--document", default=None, help="Path to the PDF document to ingest before evaluation.")
    return parser.parse_args()


def load_samples(dataset_path: Path) -> list[dict[str, str]]:
    samples = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(samples, list) or not samples:
        raise ValueError("Evaluation dataset must be a non-empty JSON array.")
    return samples


def resolve_document_path(explicit_path: str | None) -> Path:
    if explicit_path:
        path = Path(explicit_path)
        if path.exists():
            return path
        raise FileNotFoundError(f"Document not found: {path}")
    for candidate in DEFAULT_DOCUMENT_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("No evaluation PDF found. Pass --document with a valid PDF path.")


def ensure_document_ingested(client: TestClient, document_path: Path) -> None:
    with document_path.open("rb") as handle:
        response = client.post(
            "/ingest/pdf",
            files={"files": (document_path.name, handle, "application/pdf")},
        )
    response.raise_for_status()


def run_queries(client: TestClient, samples: list[dict[str, str]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for sample in samples:
        payload = {
            "question": sample["query"],
            "top_k": 5,
            "use_hybrid": True,
            "use_reranker": False,
        }
        response = client.post("/query", json=payload)
        response.raise_for_status()
        result = response.json()
        records.append(
            {
                "query": sample["query"],
                "ground_truth": sample["ground_truth"],
                "answer": result["answer"],
                "abstained": result["abstained"],
                "confidence": result["confidence"],
                "route_used": result["route_used"],
                "contexts": [chunk["text"] for chunk in result["retrieved_chunks"]],
                "citations": result["citations"],
            }
        )
    return records


def build_ragas_result(records: list[dict[str, Any]], settings) -> EvaluationResult:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is required to run RAGAS evaluation.")

    dataset = Dataset.from_dict(
        {
            "user_input": [record["query"] for record in records],
            "response": [record["answer"] for record in records],
            "retrieved_contexts": [record["contexts"] for record in records],
            "reference": [record["ground_truth"] for record in records],
        }
    )

    eval_llm = ChatOpenAI(
        model=settings.llm_model or "llama-3.3-70b-versatile",
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
        temperature=0.0,
    )
    eval_embeddings = HuggingFaceEmbeddings(
        model_name=settings.embedding_model,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )

    result = evaluate(
        dataset=dataset,
        metrics=[
            Faithfulness(),
            ResponseRelevancy(),
            LLMContextPrecisionWithoutReference(),
        ],
        llm=LangchainLLMWrapper(eval_llm),
        embeddings=LangchainEmbeddingsWrapper(eval_embeddings),
        show_progress=True,
        raise_exceptions=False,
    )
    return result


def summarize_scores(result: EvaluationResult) -> dict[str, Any]:
    score_rows = result.scores
    aggregates = {
        "faithfulness": mean([float(row.get("faithfulness", 0.0) or 0.0) for row in score_rows]),
        "answer_relevancy": mean([float(row.get("answer_relevancy", 0.0) or 0.0) for row in score_rows]),
        "context_precision": mean(
            [float(row.get("llm_context_precision_without_reference", 0.0) or 0.0) for row in score_rows]
        ),
    }
    return {
        "aggregate_metrics": {key: round(value, 4) for key, value in aggregates.items()},
        "per_sample_metrics": score_rows,
        "total_tokens": result.total_tokens(),
        "total_cost": result.total_cost(),
    }


def save_results(output_path: Path, summary: dict[str, Any], records: list[dict[str, Any]], document_path: Path) -> None:
    payload = {
        "document": str(document_path),
        "dataset_size": len(records),
        "summary": summary,
        "samples": [
            {
                "query": record["query"],
                "ground_truth": record["ground_truth"],
                "answer": record["answer"],
                "abstained": record["abstained"],
                "confidence": record["confidence"],
                "route_used": record["route_used"],
                "contexts": record["contexts"],
                "citations": record["citations"],
            }
            for record in records
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    settings = get_settings()
    dataset_path = Path(args.dataset)
    output_path = Path(args.output)
    document_path = resolve_document_path(args.document)
    samples = load_samples(dataset_path)

    with TestClient(app) as client:
        ensure_document_ingested(client, document_path)
        records = run_queries(client, samples)

    ragas_result = build_ragas_result(records, settings)
    summary = summarize_scores(ragas_result)
    save_results(output_path, summary, records, document_path)

    print(f"Saved evaluation results to: {output_path}")
    print(json.dumps(summary["aggregate_metrics"], indent=2))


if __name__ == "__main__":
    main()
