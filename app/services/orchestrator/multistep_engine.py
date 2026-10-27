from __future__ import annotations

import re
import time

from app.core.schemas import Citation, ExecutedStep, QueryPlanStep
from app.services.guardrails.abstain import should_abstain
from app.services.guardrails.citation import build_citations
from app.services.guardrails.confidence import compute_confidence


class MultiStepQueryEngine:
    def __init__(self, settings, dense_retriever, hybrid_retriever, reranker) -> None:
        self.settings = settings
        self.dense_retriever = dense_retriever
        self.hybrid_retriever = hybrid_retriever
        self.reranker = reranker

    def execute(
        self,
        question: str,
        plan: list[QueryPlanStep],
        *,
        use_hybrid: bool,
        use_reranker: bool,
        top_k: int,
        workspace_id: str | None = None,
        document_ids: list[str] | None = None,
        tenant_id: str | None = None,
        objective_profile: str | None = None,
    ) -> tuple[list[ExecutedStep], list, dict[str, float]]:
        steps: list[ExecutedStep] = []
        aggregate_context: list = []
        total_start = time.perf_counter()
        for plan_step in plan:
            if plan_step.type == "synthesis":
                steps.append(
                    ExecutedStep(
                        step=plan_step.step,
                        query=plan_step.query,
                        type="synthesis",
                        retrieved_chunks=[],
                        selected_chunks=[],
                        citations=self._build_aggregate_citations(aggregate_context),
                        confidence=compute_confidence(aggregate_context, citation_count=len(self._build_aggregate_citations(aggregate_context))) if aggregate_context else 0.0,
                        coverage=1.0 if aggregate_context else 0.0,
                        abstained=not bool(aggregate_context),
                        latency_ms={"total": 0.0},
                        notes=plan_step.notes,
                    )
                )
                continue

            step_start = time.perf_counter()
            candidate_pool = max(self.settings.retrieval_candidate_pool, top_k)
            retrieve_start = time.perf_counter()
            retriever = self.hybrid_retriever if use_hybrid else self.dense_retriever
            candidates = retriever.retrieve(
                plan_step.query or question,
                top_k=candidate_pool,
                workspace_id=workspace_id,
                document_ids=document_ids,
                tenant_id=tenant_id,
                objective_profile=objective_profile,
            )
            retrieval_ms = (time.perf_counter() - retrieve_start) * 1000

            rerank_start = time.perf_counter()
            reranked = candidates
            if use_reranker and candidates:
                try:
                    reranked = self.reranker.rerank(plan_step.query or question, candidates, top_n=min(candidate_pool, len(candidates)))
                except Exception:
                    reranked = candidates
            reranking_ms = (time.perf_counter() - rerank_start) * 1000

            selected = self._dynamic_context_selection(reranked, self.settings.max_context_chunks)
            citations = build_citations(selected)
            coverage = self._question_coverage(plan_step.query or question, selected)
            confidence = round(compute_confidence(selected, citation_count=len(citations)) * coverage, 4)
            abstained = should_abstain(
                confidence,
                self.settings.min_confidence_to_answer,
                len(selected),
                coverage=coverage,
                grounding_score=1.0,
                citation_count=len(citations),
            )
            aggregate_context = self._merge_unique_chunks(aggregate_context, selected)
            steps.append(
                ExecutedStep(
                    step=plan_step.step,
                    query=plan_step.query,
                    type="retrieve",
                    retrieved_chunks=candidates,
                    selected_chunks=selected,
                    citations=citations,
                    confidence=confidence,
                    coverage=coverage,
                    abstained=abstained,
                    latency_ms={
                        "retrieval": retrieval_ms,
                        "reranking": reranking_ms,
                        "total": (time.perf_counter() - step_start) * 1000,
                    },
                    notes=plan_step.notes,
                )
            )
        latencies = {"total": (time.perf_counter() - total_start) * 1000}
        return steps, aggregate_context, latencies

    def _merge_unique_chunks(self, existing: list, incoming: list) -> list:
        merged = {chunk.chunk_id: chunk for chunk in existing}
        for chunk in incoming:
            if chunk.chunk_id not in merged:
                merged[chunk.chunk_id] = chunk
        return list(merged.values())

    def _build_aggregate_citations(self, chunks: list) -> list[Citation]:
        return build_citations(chunks)

    def _dynamic_context_selection(self, chunks, max_context_chunks: int):
        if not chunks:
            return []
        selected = [chunks[0]]
        last_score = chunks[0].rerank_score or chunks[0].combined_score or chunks[0].dense_score or 0.0
        for chunk in chunks[1:]:
            current_score = chunk.rerank_score or chunk.combined_score or chunk.dense_score or 0.0
            if len(selected) >= max_context_chunks:
                break
            if last_score and current_score < last_score * 0.35 and len(selected) >= 2:
                break
            selected.append(chunk)
            last_score = current_score
        return selected

    def _question_coverage(self, question: str, chunks) -> float:
        stopwords = {
            "what",
            "which",
            "when",
            "where",
            "does",
            "about",
            "document",
            "say",
            "tell",
            "from",
            "with",
            "that",
            "this",
            "there",
            "into",
        }
        keywords = [token.lower() for token in re.findall(r"\w+", question) if len(token) > 3 and token.lower() not in stopwords]
        if not keywords:
            return 1.0
        combined_text = " ".join(chunk.text.lower() for chunk in chunks)
        matched = sum(1 for token in keywords if token in combined_text)
        return matched / len(keywords)
