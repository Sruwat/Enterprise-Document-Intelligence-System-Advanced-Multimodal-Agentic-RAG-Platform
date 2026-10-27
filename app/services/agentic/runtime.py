from __future__ import annotations

import time
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from app.core.logging import get_logger
from app.core.schemas import AgentRun, AgentStep, ChunkRecord, ExecutedStep, QueryRequest, QueryResponse, RetrievalTrace, UserRecord
from app.services.agentic.state import AgenticQueryServices
from app.services.guardrails.abstain import should_abstain
from app.services.guardrails.citation import build_citations, build_evidence
from app.services.guardrails.confidence import compute_confidence
from app.services.llm.fallback_provider import GroundedFallbackLLMProvider
from app.services.language import LanguagePreferenceService
from app.services.planner.query_understanding import QueryUnderstandingService
from app.services.retrieval.citation_verifier import CitationVerifier
from app.services.retrieval.graph_enricher import GraphEvidenceEnricher
from app.services.retrieval.query_modes import QueryModeResolver
from app.services.retrieval.query_rewriter import QueryRewriter
from app.services.streaming import sse_event
from app.api.rbac import require_permission

logger = get_logger(__name__)

def _query_documents_runtime(
    request: QueryRequest,
    settings,
    agent_orchestrator,
    router_service,
    dense_retriever,
    hybrid_retriever,
    reranker,
    planner,
    multistep_engine,
    session_memory,
    primary_llm,
    fallback_llm,
    graph_repository,
    eval_logger,
    metadata_store,
    redis_service,
    query_cache,
    context_agent,
    retrieval_agent,
    evidence_agent,
    legal_agent,
    study_agent,
    enterprise_agent,
    synthesis_agent,
    agentic_engine,
    user: UserRecord,
):
    orchestration_run_id = None
    if settings.enable_real_orchestrator:
        orchestration_run_id = agent_orchestrator.start_run(request, user, redis_service=redis_service)
    start = time.perf_counter()
    try:
        route_start = time.perf_counter()
        workspace = require_permission(request.workspace_id, "document.query", user, metadata_store)
    except Exception as exc:
        if orchestration_run_id:
            agent_orchestrator.fail_run(orchestration_run_id=orchestration_run_id, request=request, error=exc, redis_service=redis_service)
        raise
    if request.session_id:
        stored_session = metadata_store.get_chat_session(request.session_id)
        if stored_session and stored_session.workspace_id != request.workspace_id:
            raise HTTPException(status_code=403, detail="Chat session does not belong to this knowledge space.")
    else:
        stored_session = None
    language_resolution = LanguagePreferenceService().resolve(question=request.question, request=request, user=user, session=stored_session)
    understanding = QueryUnderstandingService().understand(
        request.question,
        language=request.language,
        input_language=language_resolution.input_language,
        response_language=language_resolution.response_language,
        explanation_level=request.explanation_level,
        answer_mode=request.answer_mode,
    )
    effective_session_id = request.session_id or "default"
    agent_steps = []
    user_context, context_step = context_agent.build(
        session_id=effective_session_id,
        workspace_id=request.workspace_id,
        objective_profile=request.objective_profile,
        user_goal=request.user_goal,
    )
    agent_steps.append(context_step)
    route_decision = router_service.route(request.question, session_id=effective_session_id) if settings.enable_router else None
    route_used = route_decision.route if route_decision else "factual"
    if route_used not in {"follow_up", "translation"} and _is_persistent_follow_up(request.question, user_context):
        route_used = "follow_up"
    target_top_k = (
        request.top_k
        if "top_k" in request.model_fields_set
        else (route_decision.requested_top_k if route_decision else settings.default_top_k)
    )
    if understanding.route_hint:
        route_used = understanding.route_hint
    if request.route_hint in {"factual", "summary", "visual_question", "table_analysis", "chart_analysis", "comparison", "scenario", "quiz", "translation", "multi_hop", "analytical", "follow_up", "unclear"}:
        route_used = request.route_hint
    mode_policy = QueryModeResolver().resolve(request, settings)
    has_visual_request = route_used in {"visual_question", "chart_analysis", "table_analysis"} or any(
        word in request.question.lower() for word in ("image", "figure", "visual", "chart", "graph", "table")
    )
    retrieval_plan, retrieval_step = retrieval_agent.plan(
        route_used=route_used,
        objective_profile=request.objective_profile,
        analysis_mode=request.analysis_mode,
        requested_top_k=target_top_k,
        has_visual_request=has_visual_request,
        context=user_context,
    )
    agent_steps.append(retrieval_step)
    pipeline, planner_step = agent_orchestrator.plan_pipeline(
        request=request,
        route_used=route_used,
        retrieval_plan=retrieval_plan,
        needs_graph=bool(getattr(graph_repository, "enabled", False)),
    )
    agent_steps.append(planner_step)
    agent_plan, tool_trace, agentic_step = agentic_engine.build_contract(
        route_used=route_used,
        objective_profile=request.objective_profile,
        analysis_mode=request.analysis_mode,
        retrieval_strategy=str(retrieval_plan.get("strategy") or "hybrid"),
        pipeline=pipeline,
        graph_enabled=bool(getattr(graph_repository, "enabled", False) or retrieval_plan.get("use_graph")),
    )
    agent_steps.append(agentic_step)
    target_top_k = int(request.top_k if "top_k" in request.model_fields_set else min(int(retrieval_plan["top_k"]), mode_policy.context_k))
    use_hybrid = settings.enable_hybrid if request.use_hybrid is None else request.use_hybrid
    use_reranker = mode_policy.use_reranker
    latencies = {"routing": (time.perf_counter() - route_start) * 1000}

    executed_steps: list[ExecutedStep] = []
    candidates = []
    reranked = []
    final_chunks = []
    cache_hit = False
    reranker_info = {
        "requested": bool(use_reranker),
        "used": False,
        "skipped_reason": None,
        "model_path": str(Path(settings.reranker_model_path)),
        "max_candidates": mode_policy.rerank_k,
    }
    effective_query = _augment_query_with_memory(understanding.retrieval_query, route_used, session_memory, effective_session_id, user_context)
    rewrite_queries = QueryRewriter().expand(
        effective_query,
        interpreted_query=understanding.interpreted_query,
        route_used=route_used,
        objective_profile=request.objective_profile,
    )
    graph_facts = _search_graph_memory(
        graph_repository,
        effective_query,
        tenant_id=user.tenant_id,
        workspace_id=request.workspace_id,
        enabled=bool(mode_policy.use_graph and retrieval_plan.get("use_graph")),
        limit=min(target_top_k, 12),
    )
    graph_chunks = GraphEvidenceEnricher().facts_to_chunks(graph_facts, workspace_id=request.workspace_id, limit=min(target_top_k, 12))
    if graph_facts:
        agent_steps.append(agent_orchestrator.graph_trace_step(graph_facts))

    if mode_policy.use_multistep and route_used in {"comparison", "multi_hop", "analytical", "follow_up", "scenario", "quiz"}:
        planning_start = time.perf_counter()
        plan = planner.plan(effective_query, route_used, session_id=effective_session_id)
        latencies["planning"] = (time.perf_counter() - planning_start) * 1000
        executed_steps, final_chunks, step_latencies = multistep_engine.execute(
            request.question,
            plan,
            use_hybrid=use_hybrid,
            use_reranker=use_reranker,
            top_k=target_top_k,
            workspace_id=request.workspace_id,
            document_ids=request.document_ids,
            tenant_id=user.tenant_id,
            objective_profile=request.objective_profile,
        )
        latencies.update({f"multistep_{key}": value for key, value in step_latencies.items()})
        first_retrieval_step = next((step for step in executed_steps if step.type == "retrieve"), None)
        last_retrieval_step = next((step for step in reversed(executed_steps) if step.type == "retrieve"), None)
        candidates = first_retrieval_step.retrieved_chunks if first_retrieval_step else []
        reranked = last_retrieval_step.selected_chunks if last_retrieval_step else []
    else:
        retrieve_start = time.perf_counter()
        candidate_pool = max(mode_policy.candidate_pool, target_top_k)
        retriever = hybrid_retriever if use_hybrid else dense_retriever
        cache_key = _retrieval_cache_key(
            query_cache,
            settings=settings,
            tenant_id=user.tenant_id,
            workspace_id=request.workspace_id,
            question=effective_query,
            document_ids=request.document_ids,
            route_used=route_used,
            objective_profile=request.objective_profile,
            analysis_mode=request.analysis_mode,
            top_k=candidate_pool,
            metadata_store=metadata_store,
        )
        cached_payload = None if settings.retrieval_cache_bypass else query_cache.get(cache_key)
        if cached_payload:
            candidates = _chunks_from_cache(cached_payload.get("candidates", []))
            cache_hit = True
            latencies["retrieval_cache"] = 0.0
        else:
            candidates = _retrieve_multi_query(
                retriever,
                rewrite_queries or [effective_query],
                top_k=candidate_pool,
                workspace_id=request.workspace_id,
                document_ids=request.document_ids,
                tenant_id=user.tenant_id,
                objective_profile=request.objective_profile,
            )
            query_cache.set(cache_key, {"candidates": [chunk.model_dump(mode="json") for chunk in candidates]})
        candidates = _merge_chunk_lists(candidates, graph_chunks, limit=max(candidate_pool, len(candidates) + len(graph_chunks)))
        if not candidates:
            for retry_query in agent_orchestrator.retry_queries(
                effective_query,
                route_used=route_used,
                objective_profile=request.objective_profile,
                response_language=understanding.answer_language,
            )[1:]:
                candidates = _retrieve_multi_query(
                    retriever,
                    [retry_query],
                    top_k=candidate_pool,
                    workspace_id=request.workspace_id,
                    document_ids=request.document_ids,
                    tenant_id=user.tenant_id,
                    objective_profile=request.objective_profile,
                )
                candidates = _merge_chunk_lists(candidates, graph_chunks, limit=max(candidate_pool, len(candidates) + len(graph_chunks)))
                if candidates:
                    agent_steps.append(
                        AgentStep(
                            step_id=str(uuid.uuid4()),
                            agent_name="PlannerAgent",
                            action="retry_retrieval_with_expanded_query",
                            output_summary="Expanded query recovered retrieval candidates.",
                            metadata={"retry_query": retry_query, "candidate_count": len(candidates)},
                        )
                    )
                    break
        latencies["retrieval"] = (time.perf_counter() - retrieve_start) * 1000

        rerank_start = time.perf_counter()
        reranked = candidates
        if use_reranker and not candidates:
            reranker_info["skipped_reason"] = "no_candidates"
        elif use_reranker and candidates:
            try:
                rerank_top_n = min(mode_policy.rerank_k or candidate_pool, candidate_pool, len(candidates))
                reranked = reranker.rerank(effective_query, candidates[:rerank_top_n], top_n=rerank_top_n)
                reranker_info["used"] = True
                reranker_info["status"] = getattr(reranker, "last_status", None)
            except Exception as exc:
                logger.exception("reranker_failed", extra={"model_path": reranker_info["model_path"]})
                reranker_info["skipped_reason"] = str(exc)
                if mode_policy.reranker_required:
                    raise HTTPException(status_code=503, detail=f"Reranker failed: {exc}") from exc
                reranked = candidates
        else:
            reranker_info["skipped_reason"] = "disabled"
        latencies["reranking"] = (time.perf_counter() - rerank_start) * 1000

        final_chunks = _dynamic_context_selection(reranked, route_used, min(settings.max_context_chunks, mode_policy.context_k))

    context_start = time.perf_counter()
    final_chunks = _merge_graph_evidence(final_chunks, [] if graph_chunks else graph_facts, limit=min(settings.max_context_chunks, mode_policy.context_k))
    final_chunks = _prioritize_answer_evidence(request.question, final_chunks)
    citations = build_citations(final_chunks)
    citation_verification = CitationVerifier().verify(answer="", citations=citations, chunks=final_chunks)
    evidence_kind = "chart" if route_used == "chart_analysis" else "table" if route_used == "table_analysis" else None
    show_visual_cards = request.include_visual_evidence and route_used in {"visual_question", "chart_analysis", "table_analysis"}
    evidence, visual_cards = build_evidence(
        final_chunks,
        include_visual=show_visual_cards,
        evidence_kind=evidence_kind,
    )
    latencies["context_building"] = (time.perf_counter() - context_start) * 1000
    objective_note = ""
    if request.objective_profile == "legal":
        objective_note, objective_step = legal_agent.annotate(request.question, final_chunks)
        agent_steps.append(objective_step)
    elif request.objective_profile == "research":
        objective_note, objective_step = study_agent.annotate(request.question, final_chunks)
        agent_steps.append(objective_step)
    elif request.objective_profile == "enterprise":
        objective_note, objective_step = enterprise_agent.annotate(request.question, final_chunks)
        agent_steps.append(objective_step)
    coverage_question = understanding.interpreted_query or request.question
    coverage = _effective_coverage(coverage_question, final_chunks, route_used)
    confidence = _effective_confidence(
        compute_confidence(final_chunks, citation_count=len(citations)),
        coverage,
        route_used,
        final_chunks,
        len(citations),
        settings.min_confidence_to_answer,
    )
    abstained = should_abstain(
        confidence,
        settings.min_confidence_to_answer,
        len(final_chunks),
        coverage=coverage,
        grounding_score=1.0,
        citation_count=len(citations),
    )
    if citations and not citation_verification["all_verified"]:
        confidence = min(confidence, 0.2)
        abstained = True
    if not executed_steps:
        executed_steps = [
            ExecutedStep(
                step=1,
                query=effective_query,
                type="retrieve",
                retrieved_chunks=candidates,
                selected_chunks=final_chunks,
                citations=citations,
                confidence=confidence,
                coverage=coverage,
                abstained=abstained,
                latency_ms={
                    "retrieval": latencies.get("retrieval", 0.0),
                    "reranking": latencies.get("reranking", 0.0),
                    "total": latencies.get("retrieval", 0.0) + latencies.get("reranking", 0.0),
                },
                notes="Single-step retrieval execution.",
            )
        ]

    answer_start = time.perf_counter()
    local_only = workspace.private_mode or not workspace.external_ai_allowed or _final_context_requires_private_processing(final_chunks)
    active_llm = GroundedFallbackLLMProvider() if local_only else primary_llm
    if abstained:
        answer = _abstain_message(understanding.answer_language)
    else:
        contexts = [
            f"[Source: {chunk.filename} p.{chunk.page_number} {chunk.chunk_id}; content_type={chunk.metadata.get('content_type', 'text')}]\n{chunk.text}"
            for chunk in final_chunks
        ]
        response_preferences, synthesis_step = synthesis_agent.build_preferences(
            language=understanding.answer_language,
            explanation_level=understanding.explanation_level,
            answer_mode=request.answer_mode,
            intent=route_used,
            objective_profile=request.objective_profile,
            analysis_mode=request.analysis_mode,
            context=user_context,
            objective_note=objective_note,
        )
        agent_steps.append(synthesis_step)
        try:
            answer = active_llm.generate(request.question, contexts, require_citations=True, response_preferences=response_preferences)
        except Exception as exc:
            if fallback_llm is None or local_only:
                raise HTTPException(status_code=502, detail=f"Primary LLM failed: {exc}") from exc
            active_llm = fallback_llm
            answer = fallback_llm.generate(request.question, contexts, require_citations=True, response_preferences=response_preferences)
        grounding_score = _evidence_grounding_score(answer, route_used, citations, visual_cards)
        confidence = round(min(confidence, grounding_score), 4)
        abstained = should_abstain(
            confidence,
            settings.min_confidence_to_answer,
            len(final_chunks),
            coverage=coverage,
            grounding_score=grounding_score,
            citation_count=len(citations),
        )
        if abstained:
            answer = _abstain_message(understanding.answer_language)
    force_abstain, verified_confidence, verifier_step = agent_orchestrator.verification_step(
        answer=answer,
        confidence=confidence,
        citations=citations,
        final_context_size=len(final_chunks),
        route_used=route_used,
        objective_profile=request.objective_profile,
        min_confidence=settings.min_confidence_to_answer,
    )
    agent_steps.append(verifier_step)
    if force_abstain:
        confidence = verified_confidence
        abstained = True
        answer = _abstain_message(understanding.answer_language)
    verification = agentic_engine.verify_answer(
        answer=answer,
        citations=citations,
        confidence=confidence,
        final_context_size=len(final_chunks),
    )
    citation_verification = CitationVerifier().verify(answer=answer, citations=citations, chunks=final_chunks)
    verification = {**verification, **citation_verification}
    if verification.get("grounding_status") == "blocked" or not citation_verification["all_verified"]:
        confidence = min(confidence, float(verification.get("confidence", confidence) or 0.0), 0.2)
        abstained = True
        answer = _abstain_message(understanding.answer_language)
        verification["grounding_status"] = "blocked"
        verification["confidence"] = confidence
    latencies["generation"] = (time.perf_counter() - answer_start) * 1000
    latencies["total"] = (time.perf_counter() - start) * 1000

    if not abstained:
        session_memory.add_turn(effective_session_id, request.question, answer)
    context_agent.remember_turn(
        session_id=effective_session_id,
        workspace_id=request.workspace_id,
        objective_profile=request.objective_profile,
        question=request.question,
        answer=answer,
        user_goal=request.user_goal,
        user_id=user.user_id,
        input_language=understanding.input_language,
        response_language=understanding.answer_language,
        interpreted_query=understanding.interpreted_query,
    )
    evidence_canvas = None
    if request.return_evidence_canvas:
        evidence_canvas, evidence_step = evidence_agent.build_canvas(
            chunks=final_chunks,
            citations=citations,
            confidence=confidence,
            route_used=route_used,
            include_visual=request.include_visual_evidence,
            answer_preview=answer,
        )
        agent_steps.append(evidence_step)
        evidence_canvas.agent_steps = agent_steps
    agent_run = AgentRun(
        run_id=str(uuid.uuid4()),
        session_id=effective_session_id,
        workspace_id=request.workspace_id,
        objective_profile=request.objective_profile,
        analysis_mode=request.analysis_mode,
        steps=agent_steps,
        created_at=datetime.utcnow(),
        metadata={"route_used": route_used, "retrieval_strategy": retrieval_plan.get("strategy")},
    )
    if not settings.enable_real_orchestrator:
        metadata_store.log_agent_run(agent_run)

    trace = RetrievalTrace(
        route_used=route_used,
        retrieved_candidates=candidates,
        reranked_candidates=reranked,
        final_contexts=final_chunks,
        latency_ms=latencies,
        provider=getattr(active_llm, "last_call_info", None).provider if getattr(active_llm, "last_call_info", None) else active_llm.provider_name,
        model=getattr(active_llm, "last_call_info", None).model if getattr(active_llm, "last_call_info", None) else active_llm.model_name,
        intent=route_used,
        step_count=len(executed_steps),
        steps=executed_steps,
        final_context_size=len(final_chunks),
        session_id=effective_session_id,
        workspace_id=request.workspace_id,
    )
    response = QueryResponse(
        answer=answer,
        citations=citations,
        confidence=confidence,
        abstained=abstained,
        route_used=route_used,
        retrieved_chunks=final_chunks,
        latency_ms=latencies,
        intent=route_used,
        steps=executed_steps if request.return_steps else [],
        final_context_size=len(final_chunks),
        retrieval_metadata={
            "reranker": reranker_info,
            "workspace_id": request.workspace_id,
            "document_ids": request.document_ids,
            "query_mode": mode_policy.mode,
            "mode_policy": mode_policy.__dict__,
            "private_mode": workspace.private_mode,
            "external_ai_allowed": workspace.external_ai_allowed,
            "provider": active_llm.provider_name,
            "model": active_llm.model_name,
            "objective_profile": request.objective_profile,
            "analysis_mode": request.analysis_mode,
            "retrieval_strategy": retrieval_plan.get("strategy"),
            "input_language": understanding.input_language,
            "response_language": understanding.answer_language,
            "language_source": language_resolution.source,
            "orchestration_pipeline": pipeline,
            "graph_fact_count": len(graph_facts),
            "rewrite_queries": rewrite_queries,
            "retrieval_trace": {
                "candidate_count": len(candidates),
                "reranked_count": len(reranked),
                "final_context_count": len(final_chunks),
                "graph_candidate_count": len(graph_chunks),
                "latency_ms": latencies,
            },
            "graph_contribution": {
                "fact_count": len(graph_facts),
                "candidate_count": len(graph_chunks),
                "selected_count": len([chunk for chunk in final_chunks if chunk.metadata.get("content_type") == "graph_fact"]),
            },
            "cache_hit": cache_hit,
            "cache": query_cache.status(),
            "citation_verification": citation_verification,
            "tool_trace": tool_trace,
            "grounding_status": verification.get("grounding_status"),
        },
        interpreted_query=understanding.interpreted_query,
        answer_language=understanding.answer_language,
        evidence=evidence,
        visual_cards=visual_cards,
        evidence_canvas=evidence_canvas,
        agent_run=agent_run,
        agent_plan=agent_plan,
        tool_trace=tool_trace,
        verification=verification,
        grounding_status=verification.get("grounding_status", "unknown"),
        needs_clarification=understanding.needs_clarification or not final_chunks,
        suggested_followups=_suggest_followups(route_used, bool(final_chunks)),
    )
    if settings.enable_real_orchestrator and orchestration_run_id:
        response = agent_orchestrator.finalize_response(
            orchestration_run_id=orchestration_run_id,
            request=request,
            response=response,
            user=user,
            metadata_store=metadata_store,
            redis_service=redis_service,
        )
    query_id = eval_logger.log_query(request.question, response, trace)
    logger.info(
        "query_completed",
        extra={
            "query_id": query_id,
            "intent": route_used,
            "number_of_steps": len(executed_steps),
            "retrieval_time": round(latencies.get("retrieval", latencies.get("multistep_total", 0.0)), 2),
            "generation_time": round(latencies.get("generation", 0.0), 2),
            "total_time": round(latencies.get("total", 0.0), 2),
            "provider_used": trace.provider,
            "abstained": abstained,
            "final_context_size": len(final_chunks),
            "fallback_used": trace.provider != getattr(primary_llm, "provider_name", None),
        },
    )
    return response

def _stream_query_native(
    *,
    request: QueryRequest,
    settings,
    router_service,
    dense_retriever,
    hybrid_retriever,
    reranker,
    session_memory,
    primary_llm,
    fallback_llm,
    graph_repository,
    eval_logger,
    metadata_store,
    redis_service,
    query_cache,
    context_agent,
    retrieval_agent,
    evidence_agent,
    legal_agent,
    study_agent,
    enterprise_agent,
    synthesis_agent,
    agent_orchestrator,
    agentic_engine,
    user: UserRecord,
):
    start = time.perf_counter()
    stream_run_id = str(uuid.uuid4())
    effective_session_id = request.session_id or "default"
    try:
        yield sse_event("agent_stage", {"stage": "auth", "label": "checking workspace permissions"})
        workspace = require_permission(request.workspace_id, "document.query", user, metadata_store)
        language_resolution = LanguagePreferenceService().resolve(question=request.question, request=request, user=user, session=None)
        understanding = QueryUnderstandingService().understand(
            request.question,
            language=request.language,
            input_language=language_resolution.input_language,
            response_language=language_resolution.response_language,
            explanation_level=request.explanation_level,
            answer_mode=request.answer_mode,
        )
        user_context, context_step = context_agent.build(
            session_id=effective_session_id,
            workspace_id=request.workspace_id,
            objective_profile=request.objective_profile,
            user_goal=request.user_goal,
        )
        route_decision = router_service.route(request.question, session_id=effective_session_id) if settings.enable_router else None
        route_used = request.route_hint or understanding.route_hint or (route_decision.route if route_decision else "factual")
        mode_policy = QueryModeResolver().resolve(request, settings)
        target_top_k = request.top_k if "top_k" in request.model_fields_set else min((route_decision.requested_top_k if route_decision else settings.default_top_k), mode_policy.context_k)
        retrieval_plan, retrieval_step = retrieval_agent.plan(
            route_used=route_used,
            objective_profile=request.objective_profile,
            analysis_mode=request.analysis_mode,
            requested_top_k=target_top_k,
            has_visual_request=False,
            context=user_context,
        )
        pipeline, planner_step = agent_orchestrator.plan_pipeline(
            request=request,
            route_used=route_used,
            retrieval_plan=retrieval_plan,
            needs_graph=bool(getattr(graph_repository, "enabled", False)),
        )
        agent_plan, tool_trace, agentic_step = agentic_engine.build_contract(
            route_used=route_used,
            objective_profile=request.objective_profile,
            analysis_mode=request.analysis_mode,
            retrieval_strategy=str(retrieval_plan.get("strategy") or "hybrid"),
            pipeline=pipeline,
            graph_enabled=bool(getattr(graph_repository, "enabled", False) or retrieval_plan.get("use_graph")),
        )
        yield sse_event("agent_stage", {"stage": "planned", "agent_plan": agent_plan, "tool_trace": tool_trace})
        rewrite_queries = QueryRewriter().expand(
            understanding.retrieval_query,
            interpreted_query=understanding.interpreted_query,
            route_used=route_used,
            objective_profile=request.objective_profile,
        )
        yield sse_event("retrieval_started", {"query": understanding.retrieval_query, "rewrite_queries": rewrite_queries, "top_k": target_top_k})
        retrieval_start = time.perf_counter()
        use_hybrid = settings.enable_hybrid if request.use_hybrid is None else request.use_hybrid
        retriever = hybrid_retriever if use_hybrid else dense_retriever
        cache_hit = False
        candidate_pool = max(mode_policy.candidate_pool, target_top_k)
        cache_key = _retrieval_cache_key(
            query_cache,
            settings=settings,
            tenant_id=user.tenant_id,
            workspace_id=request.workspace_id,
            question=understanding.retrieval_query,
            document_ids=request.document_ids,
            route_used=route_used,
            objective_profile=request.objective_profile,
            analysis_mode=request.analysis_mode,
            top_k=candidate_pool,
            metadata_store=metadata_store,
        )
        cached_payload = None if settings.retrieval_cache_bypass else query_cache.get(cache_key)
        if cached_payload:
            candidates = _chunks_from_cache(cached_payload.get("candidates", []))
            cache_hit = True
        else:
            candidates = _retrieve_multi_query(
                retriever,
                rewrite_queries or [understanding.retrieval_query],
                top_k=candidate_pool,
                workspace_id=request.workspace_id,
                document_ids=request.document_ids,
                tenant_id=user.tenant_id,
                objective_profile=request.objective_profile,
            )
            query_cache.set(cache_key, {"candidates": [chunk.model_dump(mode="json") for chunk in candidates]})
        graph_facts = _search_graph_memory(
            graph_repository,
            understanding.retrieval_query,
            tenant_id=user.tenant_id,
            workspace_id=request.workspace_id,
            enabled=bool(mode_policy.use_graph and retrieval_plan.get("use_graph")),
            limit=min(target_top_k, 12),
        )
        graph_chunks = GraphEvidenceEnricher().facts_to_chunks(graph_facts, workspace_id=request.workspace_id, limit=min(target_top_k, 12))
        candidates = _merge_chunk_lists(candidates, graph_chunks, limit=max(candidate_pool, len(candidates) + len(graph_chunks)))
        reranked = candidates
        reranker_info = {"requested": bool(mode_policy.use_reranker), "used": False, "max_candidates": mode_policy.rerank_k, "skipped_reason": None}
        if mode_policy.use_reranker and candidates:
            rerank_top_n = min(mode_policy.rerank_k or candidate_pool, candidate_pool, len(candidates))
            reranked = reranker.rerank(understanding.retrieval_query, candidates[:rerank_top_n], top_n=rerank_top_n)
            reranker_info["used"] = True
            reranker_info["status"] = getattr(reranker, "last_status", None)
        elif not mode_policy.use_reranker:
            reranker_info["skipped_reason"] = "disabled_by_query_mode"
        final_chunks = _dynamic_context_selection(reranked, route_used, min(settings.max_context_chunks, mode_policy.context_k))
        final_chunks = _merge_graph_evidence(final_chunks, [] if graph_chunks else graph_facts, limit=min(settings.max_context_chunks, mode_policy.context_k))
        final_chunks = _prioritize_answer_evidence(request.question, final_chunks)
        citations = build_citations(final_chunks)
        citation_verification = CitationVerifier().verify(answer="", citations=citations, chunks=final_chunks)
        yield sse_event("retrieval_completed", {"candidate_count": len(candidates), "context_count": len(final_chunks), "citation_count": len(citations), "graph_candidate_count": len(graph_chunks)})
        for citation in citations:
            yield sse_event("citation", citation.model_dump(mode="json"))
        confidence = compute_confidence(final_chunks, citation_count=len(citations))
        coverage = _effective_coverage(request.question, final_chunks, route_used)
        confidence = _effective_confidence(confidence, coverage, route_used, final_chunks, len(citations), settings.min_confidence_to_answer)
        abstained = should_abstain(confidence, settings.min_confidence_to_answer, len(final_chunks), coverage=coverage, grounding_score=1.0, citation_count=len(citations))
        if citations and not citation_verification["all_verified"]:
            confidence = min(confidence, 0.2)
            abstained = True
        answer_parts: list[str] = []
        local_only = workspace.private_mode or not workspace.external_ai_allowed or _final_context_requires_private_processing(final_chunks)
        active_llm = GroundedFallbackLLMProvider() if local_only else primary_llm
        contexts = [f"[Source: {chunk.filename} p.{chunk.page_number} {chunk.chunk_id}; content_type={chunk.metadata.get('content_type', 'text')}]\n{chunk.text}" for chunk in final_chunks]
        response_preferences, synthesis_step = synthesis_agent.build_preferences(
            language=understanding.answer_language,
            explanation_level=understanding.explanation_level,
            answer_mode=request.answer_mode,
            intent=route_used,
            objective_profile=request.objective_profile,
            analysis_mode=request.analysis_mode,
            context=user_context,
            objective_note="",
        )
        generation_start = time.perf_counter()
        yield sse_event("generation_started", {"provider": active_llm.provider_name, "model": active_llm.model_name})
        if abstained:
            answer = _abstain_message(understanding.answer_language)
            for token in answer.split(" "):
                yield sse_event("token", {"text": f"{token} "})
        else:
            emitted_any_token = False
            try:
                for token in active_llm.stream_generate(request.question, contexts, require_citations=True, response_preferences=response_preferences):
                    emitted_any_token = True
                    answer_parts.append(token)
                    yield sse_event("token", {"text": token})
            except Exception as exc:
                if emitted_any_token or fallback_llm is None or local_only:
                    raise
                active_llm = fallback_llm
                for token in fallback_llm.stream_generate(request.question, contexts, require_citations=True, response_preferences=response_preferences):
                    answer_parts.append(token)
                    yield sse_event("token", {"text": token})
            answer = "".join(answer_parts).strip()
        verification = agentic_engine.verify_answer(answer=answer, citations=citations, confidence=confidence, final_context_size=len(final_chunks))
        citation_verification = CitationVerifier().verify(answer=answer, citations=citations, chunks=final_chunks)
        verification = {**verification, **citation_verification}
        if verification.get("grounding_status") == "blocked" or not citation_verification["all_verified"]:
            verification["grounding_status"] = "blocked"
            verification["confidence"] = min(confidence, 0.2)
        yield sse_event("grounding_status", {"grounding_status": verification.get("grounding_status")})
        yield sse_event("verification", verification)
        evidence, visual_cards = build_evidence(final_chunks, include_visual=request.include_visual_evidence)
        evidence_canvas = None
        agent_steps = [context_step, retrieval_step, planner_step, agentic_step, synthesis_step]
        if request.return_evidence_canvas:
            evidence_canvas, evidence_step = evidence_agent.build_canvas(
                chunks=final_chunks,
                citations=citations,
                confidence=confidence,
                route_used=route_used,
                include_visual=request.include_visual_evidence,
                answer_preview=answer,
            )
            agent_steps.append(evidence_step)
            evidence_canvas.agent_steps = agent_steps
        latencies = {
            "retrieval": (time.perf_counter() - retrieval_start) * 1000,
            "generation": (time.perf_counter() - generation_start) * 1000,
            "total": (time.perf_counter() - start) * 1000,
        }
        agent_run = AgentRun(
            run_id=str(uuid.uuid4()),
            session_id=effective_session_id,
            workspace_id=request.workspace_id,
            objective_profile=request.objective_profile,
            analysis_mode=request.analysis_mode,
            steps=agent_steps,
            created_at=datetime.utcnow(),
            metadata={"route_used": route_used, "streaming": "native"},
        )
        response = QueryResponse(
            answer=answer,
            citations=citations,
            confidence=confidence,
            abstained=abstained,
            route_used=route_used,
            retrieved_chunks=final_chunks,
            latency_ms=latencies,
            intent=route_used,
            final_context_size=len(final_chunks),
            retrieval_metadata={
                "provider": active_llm.provider_name,
                "model": active_llm.model_name,
                "query_mode": mode_policy.mode,
                "mode_policy": mode_policy.__dict__,
                "reranker": reranker_info,
                "graph_fact_count": len(graph_facts),
                "rewrite_queries": rewrite_queries,
                "retrieval_trace": {
                    "candidate_count": len(candidates),
                    "reranked_count": len(reranked),
                    "final_context_count": len(final_chunks),
                    "graph_candidate_count": len(graph_chunks),
                    "latency_ms": latencies,
                },
                "graph_contribution": {
                    "fact_count": len(graph_facts),
                    "candidate_count": len(graph_chunks),
                    "selected_count": len([chunk for chunk in final_chunks if chunk.metadata.get("content_type") == "graph_fact"]),
                },
                "cache_hit": cache_hit,
                "cache": query_cache.status(),
                "citation_verification": citation_verification,
            },
            interpreted_query=understanding.interpreted_query,
            answer_language=understanding.answer_language,
            evidence=evidence,
            visual_cards=visual_cards,
            evidence_canvas=evidence_canvas,
            agent_run=agent_run,
            agent_plan=agent_plan,
            tool_trace=tool_trace,
            verification=verification,
            grounding_status=verification.get("grounding_status", "unknown"),
            suggested_followups=_suggest_followups(route_used, bool(final_chunks)),
        )
        trace = RetrievalTrace(
            route_used=route_used,
            retrieved_candidates=candidates,
            reranked_candidates=reranked,
            final_contexts=final_chunks,
            latency_ms=latencies,
            provider=active_llm.provider_name,
            model=active_llm.model_name,
            intent=route_used,
            final_context_size=len(final_chunks),
            session_id=effective_session_id,
            workspace_id=request.workspace_id,
        )
        eval_logger.log_query(request.question, response, trace)
        yield sse_event("completed", response.model_dump(mode="json"))
        yield sse_event("done", {"ok": True})
    except GeneratorExit:
        _record_stream_cancelled(
            metadata_store,
            request=request,
            user=user,
            run_id=stream_run_id,
            session_id=effective_session_id,
            elapsed_ms=(time.perf_counter() - start) * 1000,
        )
        raise
    except Exception as exc:
        logger.exception("native_stream_query_failed", extra={"workspace_id": request.workspace_id})
        yield sse_event("error", {"message": str(exc)})

def _dynamic_context_selection(chunks, route_used: str, max_context_chunks: int):
    if not chunks:
        return []
    limit = 3
    if route_used in {"summary", "comparison"}:
        limit = min(max_context_chunks, 6)
    elif route_used in {"multi_hop", "analytical"}:
        limit = min(max_context_chunks, 5)
    elif route_used == "follow_up":
        limit = min(max_context_chunks, 4)
    if route_used == "summary":
        return chunks[:limit]
    selected = [chunks[0]]
    last_score = chunks[0].rerank_score or chunks[0].combined_score or chunks[0].dense_score or 0.0
    for chunk in chunks[1:]:
        current_score = chunk.rerank_score or chunk.combined_score or chunk.dense_score or 0.0
        if len(selected) >= limit:
            break
        if last_score and current_score < last_score * 0.35 and len(selected) >= 2:
            break
        selected.append(chunk)
        last_score = current_score
    return selected


def _augment_query_with_memory(question: str, route_used: str, session_memory, session_id: str, user_context: dict | None = None) -> str:
    if route_used != "follow_up":
        return question
    context_entities = (user_context or {}).get("recent_entities", []) if user_context else []
    entities = list(context_entities[:3]) or session_memory.get_recent_entities(session_id, limit=3)
    if not entities:
        prior_messages = (user_context or {}).get("recent_messages", []) if user_context else []
        prior_text = " ".join(str(message.get("content", "")) for message in prior_messages[-4:] if isinstance(message, dict))
        if prior_text:
            return f"{question} in context of {prior_text[:500]}"
        return question
    user_goal = (user_context or {}).get("user_goal") if user_context else None
    suffix = f" for goal {user_goal}" if user_goal else ""
    return f"{question} about {' and '.join(str(entity) for entity in entities)}{suffix}"


def _is_persistent_follow_up(question: str, user_context: dict | None) -> bool:
    if not user_context:
        return False
    has_history = bool(user_context.get("recent_messages") or user_context.get("memory_summaries") or user_context.get("recent_entities"))
    if not has_history:
        return False
    lowered = question.strip().lower()
    if not lowered:
        return False
    if re.search(r"^\s*(what about|how about|and\b|also\b|it\b|they\b|them\b|those\b|that\b|this\b|same\b)", lowered):
        return True
    tokens = lowered.split()
    return len(tokens) <= 7 and any(token in {"it", "they", "them", "that", "this", "those", "same"} for token in tokens)


def _question_coverage(question: str, chunks) -> float:
    stopwords = {
        "what",
        "whats",
        "which",
        "when",
        "where",
        "does",
        "about",
        "document",
        "pdf",
        "file",
        "report",
        "summary",
        "summarize",
        "bullet",
        "bullets",
        "main",
        "major",
        "key",
        "outcome",
        "outcomes",
        "mentioned",
        "give",
        "say",
        "tell",
        "from",
        "with",
        "says",
        "about",
        "sobre",
        "dice",
        "kya",
        "hai",
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


def _effective_coverage(question: str, chunks, route_used: str) -> float:
    coverage = _question_coverage(question, chunks)
    if route_used == "summary" and chunks:
        return max(coverage, 0.9)
    lowered = question.lower()
    if chunks and re.search(r"\b(main|major|key)\b.*\b(outcomes?|findings?|points?|results?)\b", lowered):
        return max(coverage, 0.85)
    return coverage


def _effective_confidence(
    raw_confidence: float,
    coverage: float,
    route_used: str,
    chunks,
    citation_count: int,
    min_confidence: float,
) -> float:
    confidence = round(raw_confidence * coverage, 4)
    if route_used in {"summary", "comparison", "analytical", "scenario"} and chunks and citation_count and coverage >= 0.75:
        return round(max(confidence, min(min_confidence + 0.08, 0.78)), 4)
    return confidence


def _grounding_score(answer: str, question: str, chunks) -> float:
    if not answer or not chunks:
        return 0.0
    lowered_answer = answer.lower()
    if "do not have enough grounded evidence" in lowered_answer:
        return 1.0
    answer_tokens = {
        token.lower()
        for token in re.findall(r"\w+", answer)
        if len(token) > 3 and token.lower() not in {"source", "chunk", "page", "document"}
    }
    if not answer_tokens:
        return 0.0
    combined_text = " ".join(chunk.text.lower() for chunk in chunks)
    matched = sum(1 for token in answer_tokens if token in combined_text)
    lexical_overlap = matched / len(answer_tokens)
    question_overlap = _question_coverage(question, chunks)
    return round(min((lexical_overlap * 0.8) + (question_overlap * 0.2), 1.0), 4)


def _evidence_grounding_score(answer: str, route_used: str, citations, visual_cards) -> float:
    if not answer or not citations:
        return 0.0
    if route_used in {"visual_question", "chart_analysis", "table_analysis"} and not visual_cards:
        return 0.25
    has_source_marker = "[source:" in answer.lower()
    return 1.0 if has_source_marker else 0.7


def _suggest_followups(route_used: str, has_evidence: bool) -> list[str]:
    if not has_evidence:
        return ["Upload a PDF or image to begin.", "Try asking after ingestion is complete."]
    if route_used in {"visual_question", "chart_analysis", "table_analysis"}:
        return ["Explain this visual in layman terms.", "What evidence on this page supports the conclusion?"]
    return ["Explain this in Hinglish.", "Give me a simple real-life scenario from this material."]


def _abstain_message(language: str) -> str:
    if language == "hinglish":
        return "Mujhe aapke documents mein is sawal ka reliable evidence nahi mila, isliye main pakka answer nahi de sakta."
    if language == "hindi":
        return "मुझे आपके दस्तावेज़ों में इस सवाल का भरोसेमंद evidence नहीं मिला, इसलिए मैं पक्का answer नहीं दे सकता."
    if language == "spanish":
        return "No encontre evidencia confiable en sus documentos para responder con seguridad."
    return "I do not have enough grounded evidence in the retrieved documents to answer reliably."


def _prioritize_answer_evidence(question: str, chunks):
    lowered_question = question.lower()
    if any(term in lowered_question for term in ("question bank", "evaluation question", "citation map", "evidence inventory")):
        return chunks
    reference_markers = (
        "question bank",
        "evaluation question",
        "citation map",
        "evidence inventory",
        "citation validation prompt",
        "expected evidence/result",
    )
    return sorted(
        chunks,
        key=lambda chunk: any(marker in chunk.text.lower() for marker in reference_markers),
    )


def _search_graph_memory(graph_repository, query: str, *, tenant_id: str, workspace_id: str, enabled: bool, limit: int):
    if not enabled or graph_repository is None or not getattr(graph_repository, "enabled", False):
        return []
    try:
        return graph_repository.search_graph(query, tenant_id=tenant_id, workspace_id=workspace_id, limit=limit)
    except Exception:
        logger.exception("graph_memory_search_failed", extra={"workspace_id": workspace_id})
        return []


def _final_context_requires_private_processing(chunks) -> bool:
    for chunk in chunks or []:
        metadata = chunk.metadata or {}
        if metadata.get("external_processing_allowed") is False:
            return True
        page_metadata = metadata.get("page_metadata") or metadata.get("multimodal_assets") or {}
        if isinstance(page_metadata, dict) and page_metadata.get("external_processing_allowed") is False:
            return True
    return False


def _merge_graph_evidence(chunks, graph_facts, *, limit: int):
    if not graph_facts:
        return chunks
    merged = {chunk.chunk_id: chunk for chunk in chunks}
    for fact in graph_facts:
        document_id = getattr(fact, "document_id", None)
        page_number = getattr(fact, "page_number", None)
        if not document_id or not page_number:
            continue
        source = getattr(fact, "source", None)
        target = getattr(fact, "target", None)
        relationship = getattr(fact, "relationship", None)
        source_name = getattr(source, "canonical_name", "Entity")
        target_name = getattr(target, "canonical_name", None)
        relationship_type = getattr(relationship, "relationship_type", "REFERENCES")
        fact_text = f"Graph memory: {source_name}"
        if target_name:
            fact_text += f" {relationship_type} {target_name}"
        fact_text += "."
        chunk_id = f"graph-{getattr(fact, 'evidence_anchor_id', None) or document_id}-{page_number}-{len(merged)}"
        if chunk_id in merged:
            continue
        merged[chunk_id] = ChunkRecord(
            chunk_id=chunk_id,
            document_id=document_id,
            workspace_id=getattr(source, "workspace_id", "default"),
            filename=f"Graph memory for {document_id}",
            page_number=int(page_number),
            text=fact_text,
            token_count=len(fact_text.split()),
            content_type="text",
            metadata={
                "content_type": "graph_fact",
                "graph_fact": {
                    "source": source_name,
                    "source_type": getattr(source, "entity_type", None),
                    "target": target_name,
                    "target_type": getattr(target, "entity_type", None),
                    "relationship": relationship_type,
                    "evidence_anchor_id": getattr(fact, "evidence_anchor_id", None),
                },
            },
            combined_score=0.99,
        )
        if len(merged) >= limit:
            break
    return list(merged.values())[:limit]


def _stream_query_response(response: QueryResponse):
    yield _sse("metadata", {"confidence": response.confidence, "intent": response.intent, "abstained": response.abstained})
    stage_map = [
        ("retrieval", "retrieval"),
        ("reranking", "reranking"),
        ("context_building", "context building"),
        ("generation", "LLM generating"),
        ("citations_ready", "citations ready"),
    ]
    for key, label in stage_map:
        yield _sse("stage", {"stage": key, "label": label, "latency_ms": response.latency_ms.get(key)})
    yield _sse("final", response.model_dump(mode="json"))
    yield _sse("done", {"ok": True})


def _tokenize_for_stream(text: str):
    parts = re.findall(r"\S+\s*", text)
    if not parts:
        yield ""
    for part in parts:
        yield part


def _sse(event: str, payload: dict) -> str:
    return sse_event(event, payload)


def _retrieve_with_scope(retriever, question: str, **kwargs):
    try:
        return retriever.retrieve(question, **kwargs)
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        legacy_kwargs = {key: value for key, value in kwargs.items() if key in {"top_k", "workspace_id", "document_ids"}}
        return retriever.retrieve(question, **legacy_kwargs)


def _services(**kwargs) -> AgenticQueryServices:
    return AgenticQueryServices(**kwargs)


def _retrieval_cache_key(
    query_cache,
    *,
    settings,
    tenant_id: str,
    workspace_id: str,
    question: str,
    document_ids: list[str],
    route_used: str,
    objective_profile: str,
    analysis_mode: str,
    top_k: int,
    metadata_store,
) -> str:
    index_version = _workspace_index_version(metadata_store, workspace_id)
    return query_cache.retrieval_key(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        question=question,
        document_ids=document_ids,
        route=route_used,
        objective_profile=objective_profile,
        analysis_mode=analysis_mode,
        top_k=top_k,
        embedding_model=str(settings.embedding_model),
        reranker_model=str(settings.reranker_model),
        index_version=index_version,
    )


def _workspace_index_version(metadata_store, workspace_id: str) -> str:
    try:
        documents = metadata_store.list_documents(workspace_id=workspace_id)
    except Exception:
        return "unknown"
    if not documents:
        return "empty"
    latest = max(str(getattr(document, "updated_at", "") or getattr(document, "ingested_at", "") or "") for document in documents)
    return f"{len(documents)}:{latest}"


def _chunks_from_cache(items: list[dict]) -> list[ChunkRecord]:
    chunks = []
    for item in items:
        try:
            chunks.append(ChunkRecord.model_validate(item))
        except Exception:
            continue
    return chunks


def _record_stream_cancelled(metadata_store, *, request: QueryRequest, user: UserRecord, run_id: str, session_id: str, elapsed_ms: float) -> None:
    try:
        run = AgentRun(
            run_id=run_id,
            session_id=session_id,
            workspace_id=request.workspace_id,
            objective_profile=request.objective_profile,
            analysis_mode=request.analysis_mode,
            steps=[
                AgentStep(
                    step_id=str(uuid.uuid4()),
                    agent_name="AgenticQueryEngine",
                    action="stream_cancelled",
                    status="failed",
                    output_summary="Client disconnected before stream completion.",
                    metadata={"cancelled": True, "elapsed_ms": elapsed_ms, "user_id": user.user_id},
                )
            ],
            created_at=datetime.utcnow(),
            metadata={"status": "cancelled", "streaming": True, "elapsed_ms": elapsed_ms},
        )
        metadata_store.log_agent_run(run)
    except Exception:
        logger.exception("stream_cancellation_record_failed", extra={"workspace_id": request.workspace_id})


def _retrieve_multi_query(retriever, queries: list[str], **kwargs):
    merged = []
    seen: set[str] = set()
    top_k = int(kwargs.get("top_k") or 5)
    per_query_k = max(top_k // max(len(queries), 1), top_k if len(queries) == 1 else 3)
    for query in queries:
        query_kwargs = {**kwargs, "top_k": max(per_query_k, top_k)}
        for chunk in _retrieve_with_scope(retriever, query, **query_kwargs):
            if chunk.chunk_id in seen:
                continue
            chunk.metadata = {**chunk.metadata, "retrieval_query": query}
            merged.append(chunk)
            seen.add(chunk.chunk_id)
            if len(merged) >= top_k:
                return merged
    return merged


def _merge_chunk_lists(primary, secondary, *, limit: int):
    merged = {chunk.chunk_id: chunk for chunk in primary}
    for chunk in secondary:
        if chunk.chunk_id not in merged:
            merged[chunk.chunk_id] = chunk
    return sorted(
        merged.values(),
        key=lambda chunk: chunk.rerank_score or chunk.combined_score or chunk.dense_score or chunk.sparse_score or chunk.metadata.get("graph_score", 0.0) or 0.0,
        reverse=True,
    )[:limit]
