from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

IngestionStatus = Literal["processing", "indexed", "failed"]
IngestionJobStatus = Literal["uploaded", "queued", "processing", "parsing", "extracting_visuals", "embedding", "ready", "indexed", "failed"]
IntentLabel = Literal[
    "factual",
    "summary",
    "visual_question",
    "table_analysis",
    "chart_analysis",
    "comparison",
    "scenario",
    "quiz",
    "translation",
    "multi_hop",
    "analytical",
    "follow_up",
    "unclear",
]
QueryMode = Literal["single", "multistep"]
RetrievalMode = Literal["auto", "fast", "balanced", "deep"]
LanguagePreference = Literal["auto", "english", "hindi", "hinglish", "spanish"]
ExplanationLevel = Literal["layman", "normal", "deep"]
AnswerMode = Literal["answer", "summarize", "explain_visual", "compare", "scenario", "quiz_me"]
ObjectiveProfile = Literal["general", "legal", "research", "enterprise"]
AnalysisMode = Literal["quick", "deep", "agentic"]


class WorkspaceRecord(BaseModel):
    workspace_id: str
    name: str
    owner_id: str = "local-user"
    tenant_id: str = "default-tenant"
    private_mode: bool = False
    external_ai_allowed: bool = True
    created_at: datetime
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceCreateRequest(BaseModel):
    name: str = "My Knowledge Space"
    owner_id: str = "local-user"
    tenant_id: str = "default-tenant"
    private_mode: bool = False
    external_ai_allowed: bool = True


class UserRecord(BaseModel):
    user_id: str
    tenant_id: str = "default-tenant"
    email: str
    display_name: str | None = None
    avatar_url: str | None = None
    auth_provider: str = "local"
    provider_subject: str | None = None
    status: Literal["active", "disabled", "suspended"] = "active"
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)


class ApiKeyCreateRequest(BaseModel):
    name: str = "Workspace API key"
    role: Literal["admin", "analyst", "viewer", "auditor"] = "viewer"
    permissions: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class ApiKeyCreateResponse(BaseModel):
    key_id: str
    api_key: str
    masked_key: str
    name: str
    workspace_id: str
    role: str
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime


class ApiKeyRecord(BaseModel):
    key_id: str
    workspace_id: str
    name: str
    masked_key: str
    role: str
    permissions: list[str] = Field(default_factory=list)
    created_by: str
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class WorkspaceInvitationCreateRequest(BaseModel):
    email: str
    role: Literal["admin", "analyst", "viewer"] = "viewer"
    expires_at: datetime | None = None


class WorkspaceInvitationRecord(BaseModel):
    invitation_id: str
    workspace_id: str
    tenant_id: str = "default-tenant"
    email: str
    role: Literal["admin", "analyst", "viewer"] = "viewer"
    invited_by: str
    status: Literal["pending", "accepted", "revoked", "expired"] = "pending"
    expires_at: datetime
    accepted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class WorkspaceInvitationCreateResponse(WorkspaceInvitationRecord):
    invitation_token: str | None = None


class GoogleAuthUrlResponse(BaseModel):
    authorization_url: str


class GoogleCallbackRequest(BaseModel):
    code: str | None = None
    id_token: str | None = None
    state: str | None = None


class AuthResponse(BaseModel):
    user: UserRecord
    session_token: str


class TenantRecord(BaseModel):
    tenant_id: str
    name: str
    plan: str = "free"
    created_at: datetime
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestionJobRecord(BaseModel):
    job_id: str
    workspace_id: str
    filename: str
    status: IngestionJobStatus = "uploaded"
    progress: int = Field(default=0, ge=0, le=100)
    document_id: str | None = None
    message: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TextSourceRequest(BaseModel):
    title: str = "Pasted Notes"
    text: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BrowserCaptureRequest(BaseModel):
    workspace_id: str = "default"
    title: str = "Browser Page"
    url: str
    text: str = Field(min_length=1)
    selection_used: bool = False
    extension_version: str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)


class BrowserPageQueryRequest(BrowserCaptureRequest):
    question: str


class BrowserSummaryResponse(BaseModel):
    title: str
    url: str
    summary: str
    entities: list[str] = Field(default_factory=list)
    source_hash: str


class DocumentRecord(BaseModel):
    document_id: str
    workspace_id: str = "default"
    filename: str
    source_path: str
    fingerprint: str
    status: IngestionStatus = "processing"
    page_count: int
    ingested_at: datetime
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataFootprintSummary(BaseModel):
    document_id: str
    filename: str
    status: str
    document_mode: str = "knowledge_base"
    classification: str = "internal"
    original_bytes: int | None = None
    extracted_text_bytes: int = 0
    page_count: int = 0
    ocr_pages: int = 0
    chunk_count: int = 0
    vector_count: int | None = None
    graph_entity_count: int | None = None
    graph_relation_count: int | None = None
    chat_reference_count: int | None = None
    retention_policy: dict[str, Any] = Field(default_factory=dict)
    privacy_boundary: dict[str, Any] = Field(default_factory=dict)
    indexed_at: datetime | None = None
    updated_at: datetime | None = None


class DataVaultOverview(BaseModel):
    workspace_id: str
    tenant_id: str
    documents: int
    original_storage_bytes: int | None = None
    extracted_content_bytes: int = 0
    indexed_chunks: int = 0
    vector_embeddings: int | None = None
    ocr_pages: int = 0
    graph_entities: int | None = None
    graph_relationships: int | None = None
    chats: int | None = None
    temporary_documents: int = 0
    retention_policy: dict[str, Any] = Field(default_factory=dict)
    privacy_mode: str
    llm_provider_mode: str
    embedding_provider_mode: str
    storage_backend: str
    pending_purges: int = 0
    retention_expirations: int = 0
    privacy_summary: dict[str, int] = Field(default_factory=dict)
    provider_summary: dict[str, list[str]] = Field(default_factory=dict)
    documents_footprint: list[DataFootprintSummary] = Field(default_factory=list)


class DataLineageStage(BaseModel):
    stage: str
    status: str
    count: int | None = None
    bytes: int | None = None
    provider: str | None = None
    boundary: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class DataLineage(BaseModel):
    document_id: str
    workspace_id: str
    tenant_id: str
    filename: str
    stages: list[DataLineageStage] = Field(default_factory=list)
    generated_at: datetime


class DeletionRequestRecord(BaseModel):
    request_id: str
    tenant_id: str
    workspace_id: str
    document_id: str
    requested_by: str
    reason: str
    status: Literal["pending", "approved", "rejected", "cancelled", "completed"] = "pending"
    approved_by: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PurgeRequest(BaseModel):
    reason: str = "user_request"


class PurgeJobRecord(BaseModel):
    purge_job_id: str
    workspace_id: str
    document_id: str
    status: Literal["queued", "processing", "partial", "retrying", "completed", "failed", "cancelled"] = "queued"
    reason: str
    requested_by: str
    receipt: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class ChunkRecord(BaseModel):
    chunk_id: str
    document_id: str
    workspace_id: str = "default"
    filename: str
    page_number: int
    text: str
    section: str | None = None
    token_count: int = 0
    chunk_position: int | None = None
    prev_chunk_id: str | None = None
    next_chunk_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_type: str = "text"
    bbox: list[float] | None = None
    section_path: list[str] = Field(default_factory=list)
    visual_caption: str | None = None
    table_json: dict[str, Any] | None = None
    chart_series: dict[str, Any] | None = None
    risk_tags: list[str] = Field(default_factory=list)
    dense_score: float | None = None
    sparse_score: float | None = None
    rerank_score: float | None = None
    combined_score: float | None = None


class Citation(BaseModel):
    document_id: str
    filename: str
    page_number: int
    chunk_id: str
    snippet: str
    anchor_id: str | None = None
    content_type: str = "text"
    preview_path: str | None = None
    bbox: list[float] | None = None


class EvidenceItem(BaseModel):
    evidence_id: str
    document_id: str
    filename: str
    page_number: int
    content_type: str = "text"
    snippet: str
    anchor_id: str | None = None
    preview_path: str | None = None
    bbox: list[float] | None = None
    interpretation: str | None = None


class VisualEvidenceCard(BaseModel):
    evidence_id: str
    document_id: str
    filename: str
    page_number: int
    visual_type: str
    preview_path: str | None = None
    bbox: list[float] | None = None
    title: str | None = None
    interpretation: str
    plain_language_explanation: str


class EvidenceCanvas(BaseModel):
    summary: str = ""
    citations: list[Citation] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    visual_cards: list[VisualEvidenceCard] = Field(default_factory=list)
    artifact_cards: list[dict[str, Any]] = Field(default_factory=list)
    agent_steps: list["AgentStep"] = Field(default_factory=list)
    confidence: float = 0.0
    missing_evidence: list[str] = Field(default_factory=list)
    why_this_answer: str = ""


class MemoryRecord(BaseModel):
    memory_id: str
    session_id: str
    workspace_id: str = "default"
    user_id: str = "local-user"
    objective_profile: ObjectiveProfile = "general"
    memory_type: Literal["short_term", "long_term", "document", "preference"] = "short_term"
    content: str
    entities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime | None = None


class ChatMessageRecord(BaseModel):
    message_id: str
    session_id: str
    workspace_id: str = "default"
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    language: LanguagePreference = "auto"
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractedArtifact(BaseModel):
    artifact_id: str
    document_id: str
    workspace_id: str = "default"
    artifact_type: Literal["table", "chart", "figure", "clause", "risk", "timeline", "definition", "section"]
    page_number: int
    title: str | None = None
    text: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    bbox: list[float] | None = None
    created_at: datetime


class EvidenceAnchorRecord(BaseModel):
    anchor_id: str
    document_id: str
    workspace_id: str = "default"
    chunk_id: str | None = None
    artifact_id: str | None = None
    anchor_type: Literal["chunk", "artifact", "page", "figure", "table", "chart", "clause", "risk", "definition", "section"] = "chunk"
    page_number: int
    bbox: list[float] | None = None
    preview_path: str | None = None
    crop_path: str | None = None
    citation_text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AgentStep(BaseModel):
    step_id: str
    agent_name: str
    action: str
    status: Literal["planned", "running", "completed", "failed"] = "completed"
    input_summary: str | None = None
    output_summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRun(BaseModel):
    run_id: str
    session_id: str | None = None
    workspace_id: str = "default"
    objective_profile: ObjectiveProfile = "general"
    analysis_mode: AnalysisMode = "quick"
    steps: list[AgentStep] = Field(default_factory=list)
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditLogRecord(BaseModel):
    audit_id: str
    tenant_id: str = "default-tenant"
    workspace_id: str | None = None
    user_id: str = "local-user"
    event_type: str
    actor_email: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    status: Literal["success", "failure"] = "success"
    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class QueryRequest(BaseModel):
    question: str
    workspace_id: str = "default"
    document_ids: list[str] = Field(default_factory=list)
    language: LanguagePreference = "auto"
    input_language: LanguagePreference | None = None
    response_language: LanguagePreference | None = None
    explanation_level: ExplanationLevel = "normal"
    answer_mode: AnswerMode = "answer"
    objective_profile: ObjectiveProfile = "general"
    analysis_mode: AnalysisMode = "quick"
    query_mode: RetrievalMode = "balanced"
    user_goal: str | None = None
    return_evidence_canvas: bool = True
    include_visual_evidence: bool = True
    top_k: int = 5
    use_hybrid: bool | None = None
    use_reranker: bool | None = None
    route_hint: str | None = None
    mode: QueryMode = "single"
    return_steps: bool = False
    session_id: str | None = None


class ChatSessionCreateRequest(BaseModel):
    workspace_id: str = "default"
    title: str | None = None
    language: LanguagePreference = "auto"
    input_language: LanguagePreference | None = None
    response_language: LanguagePreference | None = None
    explanation_level: ExplanationLevel = "normal"
    objective_profile: ObjectiveProfile = "general"
    analysis_mode: AnalysisMode = "quick"


class ChatSessionRecord(BaseModel):
    session_id: str
    workspace_id: str
    title: str | None = None
    language: LanguagePreference = "auto"
    input_language: LanguagePreference = "auto"
    response_language: LanguagePreference = "auto"
    explanation_level: ExplanationLevel = "normal"
    objective_profile: ObjectiveProfile = "general"
    analysis_mode: AnalysisMode = "quick"
    created_at: datetime
    updated_at: datetime | None = None


class IntentDetectionResult(BaseModel):
    intent: IntentLabel
    confidence: float = 0.0
    signals: dict[str, Any] = Field(default_factory=dict)
    used_llm_refinement: bool = False
    reason: str = ""


class QueryPlanStep(BaseModel):
    step: int
    query: str | None = None
    type: Literal["retrieve", "synthesis"] = "retrieve"
    depends_on: list[int] = Field(default_factory=list)
    notes: str | None = None


class ExecutedStep(BaseModel):
    step: int
    query: str | None = None
    type: Literal["retrieve", "synthesis"] = "retrieve"
    retrieved_chunks: list[ChunkRecord] = Field(default_factory=list)
    selected_chunks: list[ChunkRecord] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = 0.0
    coverage: float = 0.0
    abstained: bool = False
    latency_ms: dict[str, float] = Field(default_factory=dict)
    notes: str | None = None


class RetrievalTrace(BaseModel):
    route_used: str
    retrieved_candidates: list[ChunkRecord] = Field(default_factory=list)
    reranked_candidates: list[ChunkRecord] = Field(default_factory=list)
    final_contexts: list[ChunkRecord] = Field(default_factory=list)
    latency_ms: dict[str, float] = Field(default_factory=dict)
    provider: str | None = None
    model: str | None = None
    intent: IntentLabel | None = None
    step_count: int = 0
    steps: list[ExecutedStep] = Field(default_factory=list)
    final_context_size: int = 0
    session_id: str | None = None
    workspace_id: str = "default"


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    confidence: float
    abstained: bool
    route_used: str
    retrieved_chunks: list[ChunkRecord]
    latency_ms: dict[str, float]
    intent: IntentLabel = "factual"
    steps: list[ExecutedStep] = Field(default_factory=list)
    final_context_size: int = 0
    retrieval_metadata: dict[str, Any] = Field(default_factory=dict)
    interpreted_query: str | None = None
    answer_language: LanguagePreference = "english"
    evidence: list[EvidenceItem] = Field(default_factory=list)
    visual_cards: list[VisualEvidenceCard] = Field(default_factory=list)
    evidence_canvas: EvidenceCanvas | None = None
    agent_run: AgentRun | None = None
    agent_plan: dict[str, Any] = Field(default_factory=dict)
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)
    grounding_status: Literal["grounded", "low_confidence", "blocked", "unknown"] = "unknown"
    needs_clarification: bool = False
    suggested_followups: list[str] = Field(default_factory=list)


class EvalRecord(BaseModel):
    query_id: str
    question: str
    ground_truth: str | None = None
    model_answer: str | None = None
    retrieved_contexts: list[ChunkRecord] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestResponse(BaseModel):
    document: DocumentRecord
    chunks_created: int
    indexed: bool
    duplicate: bool = False


class EvaluationRunRequest(BaseModel):
    dataset_path: str | None = None
    query_limit: int | None = None


class EvaluationDatasetItem(BaseModel):
    query: str
    expected_answer: str
    supporting_document_reference: dict[str, Any]
    category: str = "factual"
    expected_behavior: Literal["answer", "abstain"] = "answer"


class EvaluationCaseResult(BaseModel):
    query: str
    category: str
    expected_answer: str
    expected_behavior: Literal["answer", "abstain"] = "answer"
    supporting_document_reference: dict[str, Any] = Field(default_factory=dict)
    answer: str
    abstained: bool
    confidence: float
    intent: IntentLabel = "factual"
    steps: list[ExecutedStep] = Field(default_factory=list)
    retrieved_chunks: list[ChunkRecord] = Field(default_factory=list)
    latency_ms: dict[str, float] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)


class EvaluationRunSummary(BaseModel):
    run_id: str
    timestamp: str
    dataset_path: str
    dataset_size: int
    provider: str | None = None
    model: str | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    failures: list[dict[str, Any]] = Field(default_factory=list)


class EvaluationHistoryEntry(BaseModel):
    run_id: str
    timestamp: str
    provider: str | None = None
    model: str | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    dataset_size: int = 0


class EvaluationSummary(BaseModel):
    total_queries: int
    avg_confidence: float
    abstention_rate: float
    metrics: dict[str, float]
    recent_failures: list[dict[str, Any]]


class RouteDecision(BaseModel):
    route: IntentLabel
    objective_profile: ObjectiveProfile = "general"
    analysis_mode: AnalysisMode = "quick"
    use_multimodal: bool = False
    use_graph: bool = False
    requested_top_k: int = 5
    retrieval_strategy: str = "hybrid"
    needs_clarification: bool = False
    reason: str = ""
