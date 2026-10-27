from __future__ import annotations

import json
import time
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.auth_context import get_current_user
from app.api.rbac import require_permission
from app.core.dependencies import (
    get_app_settings,
    get_agent_orchestrator,
    get_agentic_query_engine,
    get_context_agent,
    get_dense_retriever,
    get_enterprise_agent,
    get_evidence_agent,
    get_eval_logger,
    get_fallback_llm,
    get_graph_repository,
    get_hybrid_retriever,
    get_legal_agent,
    get_metadata_store,
    get_multistep_engine,
    get_primary_llm,
    get_query_cache,
    get_query_planner,
    get_reranker,
    get_retrieval_agent,
    get_redis_service,
    get_router,
    get_session_memory,
    get_study_agent,
    get_synthesis_agent,
)
from app.core.logging import get_logger
from app.core.schemas import AgentRun, AgentStep, ChatMessageRecord, ChatSessionCreateRequest, ChatSessionRecord, ChunkRecord, ExecutedStep, QueryRequest, QueryResponse, RetrievalTrace, UserRecord
from app.services.guardrails.abstain import should_abstain
from app.services.guardrails.citation import build_citations, build_evidence
from app.services.guardrails.confidence import compute_confidence
from app.services.agentic.state import AgenticQueryServices
from app.services.llm.fallback_provider import GroundedFallbackLLMProvider
from app.services.language import LanguagePreferenceService
from app.services.planner.query_understanding import QueryUnderstandingService
from app.services.retrieval.citation_verifier import CitationVerifier
from app.services.retrieval.graph_enricher import GraphEvidenceEnricher
from app.services.retrieval.query_rewriter import QueryRewriter
from app.services.streaming import sse_event, stream_completed_response
from app.services.agentic.runtime import (
    _abstain_message,
    _augment_query_with_memory,
    _dynamic_context_selection,
    _effective_confidence,
    _effective_coverage,
    _evidence_grounding_score,
    _grounding_score,
    _is_persistent_follow_up,
    _prioritize_answer_evidence,
    _question_coverage,
)

router = APIRouter(tags=["query"])
logger = get_logger(__name__)


@router.post("/query", response_model=QueryResponse)
@router.post("/chat/query", response_model=QueryResponse)
def query_documents(
    request: QueryRequest,
    settings=Depends(get_app_settings),
    agent_orchestrator=Depends(get_agent_orchestrator),
    router_service=Depends(get_router),
    dense_retriever=Depends(get_dense_retriever),
    hybrid_retriever=Depends(get_hybrid_retriever),
    reranker=Depends(get_reranker),
    planner=Depends(get_query_planner),
    multistep_engine=Depends(get_multistep_engine),
    session_memory=Depends(get_session_memory),
    primary_llm=Depends(get_primary_llm),
    fallback_llm=Depends(get_fallback_llm),
    graph_repository=Depends(get_graph_repository),
    eval_logger=Depends(get_eval_logger),
    metadata_store=Depends(get_metadata_store),
    redis_service=Depends(get_redis_service),
    query_cache=Depends(get_query_cache),
    context_agent=Depends(get_context_agent),
    retrieval_agent=Depends(get_retrieval_agent),
    evidence_agent=Depends(get_evidence_agent),
    legal_agent=Depends(get_legal_agent),
    study_agent=Depends(get_study_agent),
    enterprise_agent=Depends(get_enterprise_agent),
    synthesis_agent=Depends(get_synthesis_agent),
    agentic_engine=Depends(get_agentic_query_engine),
    user: UserRecord = Depends(get_current_user),
):
    return agentic_engine.run(
        request=request,
        services=_services(
            settings=settings,
            agent_orchestrator=agent_orchestrator,
            router_service=router_service,
            dense_retriever=dense_retriever,
            hybrid_retriever=hybrid_retriever,
            reranker=reranker,
            planner=planner,
            multistep_engine=multistep_engine,
            session_memory=session_memory,
            primary_llm=primary_llm,
            fallback_llm=fallback_llm,
            graph_repository=graph_repository,
            eval_logger=eval_logger,
            metadata_store=metadata_store,
            redis_service=redis_service,
            query_cache=query_cache,
            context_agent=context_agent,
            retrieval_agent=retrieval_agent,
            evidence_agent=evidence_agent,
            legal_agent=legal_agent,
            study_agent=study_agent,
            enterprise_agent=enterprise_agent,
            synthesis_agent=synthesis_agent,
        ),
        user=user,
    )


@router.post("/chat/query/stream")
def stream_query_documents(
    request: QueryRequest,
    settings=Depends(get_app_settings),
    agent_orchestrator=Depends(get_agent_orchestrator),
    router_service=Depends(get_router),
    dense_retriever=Depends(get_dense_retriever),
    hybrid_retriever=Depends(get_hybrid_retriever),
    reranker=Depends(get_reranker),
    planner=Depends(get_query_planner),
    multistep_engine=Depends(get_multistep_engine),
    session_memory=Depends(get_session_memory),
    primary_llm=Depends(get_primary_llm),
    fallback_llm=Depends(get_fallback_llm),
    graph_repository=Depends(get_graph_repository),
    eval_logger=Depends(get_eval_logger),
    metadata_store=Depends(get_metadata_store),
    redis_service=Depends(get_redis_service),
    query_cache=Depends(get_query_cache),
    context_agent=Depends(get_context_agent),
    retrieval_agent=Depends(get_retrieval_agent),
    evidence_agent=Depends(get_evidence_agent),
    legal_agent=Depends(get_legal_agent),
    study_agent=Depends(get_study_agent),
    enterprise_agent=Depends(get_enterprise_agent),
    synthesis_agent=Depends(get_synthesis_agent),
    agentic_engine=Depends(get_agentic_query_engine),
    user: UserRecord = Depends(get_current_user),
):
    return StreamingResponse(
        agentic_engine.stream(
            request=request,
            services=_services(
                settings=settings,
                agent_orchestrator=agent_orchestrator,
                router_service=router_service,
                dense_retriever=dense_retriever,
                hybrid_retriever=hybrid_retriever,
                reranker=reranker,
                planner=planner,
                multistep_engine=multistep_engine,
                session_memory=session_memory,
                primary_llm=primary_llm,
                fallback_llm=fallback_llm,
                graph_repository=graph_repository,
                eval_logger=eval_logger,
                metadata_store=metadata_store,
                redis_service=redis_service,
                query_cache=query_cache,
                context_agent=context_agent,
                retrieval_agent=retrieval_agent,
                evidence_agent=evidence_agent,
                legal_agent=legal_agent,
                study_agent=study_agent,
                enterprise_agent=enterprise_agent,
                synthesis_agent=synthesis_agent,
            ),
            user=user,
        ),
        media_type="text/event-stream",
    )


@router.post("/chat/sessions", response_model=ChatSessionRecord, status_code=201)
def create_chat_session(
    request: ChatSessionCreateRequest,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> ChatSessionRecord:
    require_permission(request.workspace_id, "document.query", user, metadata_store)
    return metadata_store.create_chat_session(
        request.workspace_id,
        request.title,
        request.language,
        request.explanation_level,
        request.objective_profile,
        request.analysis_mode,
        request.input_language,
        request.response_language,
    )


@router.get("/workspaces/{workspace_id}/chat/sessions", response_model=list[ChatSessionRecord])
def list_chat_sessions(
    workspace_id: str,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> list[ChatSessionRecord]:
    require_permission(workspace_id, "workspace.read", user, metadata_store)
    return metadata_store.list_chat_sessions(workspace_id, limit=100)


@router.get("/chat/sessions/{session_id}/messages", response_model=list[ChatMessageRecord])
def list_chat_messages(
    session_id: str,
    metadata_store=Depends(get_metadata_store),
    user: UserRecord = Depends(get_current_user),
) -> list[ChatMessageRecord]:
    session = metadata_store.get_chat_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    require_permission(session.workspace_id, "workspace.read", user, metadata_store)
    return metadata_store.list_chat_messages(session_id, limit=100)




def _services(**kwargs) -> AgenticQueryServices:
    return AgenticQueryServices(**kwargs)
