export type Theme = "dark" | "light";
export type Objective = "legal" | "research" | "enterprise";
export type QueryMode = "auto" | "fast" | "balanced" | "deep";
export type Role = "user" | "assistant";

export type Workspace = { workspace_id: string; name: string; private_mode?: boolean; external_ai_allowed?: boolean };
export type User = { user_id: string; email: string; display_name?: string | null; status?: string; auth_provider?: string };

export type ChatSession = {
  session_id: string;
  workspace_id: string;
  title?: string | null;
  objective_profile?: Objective | "general";
  analysis_mode?: string;
  created_at: string;
};

export type ChatMessageRecord = { role: "user" | "assistant" | "system" | "tool"; content: string };
export type DocumentRecord = { document_id: string; filename: string; page_count: number; status: string; metadata?: Record<string, unknown> };
export type DataFootprintSummary = {
  document_id: string;
  filename: string;
  status: string;
  document_mode: string;
  classification: string;
  original_bytes?: number | null;
  extracted_text_bytes: number;
  page_count: number;
  ocr_pages: number;
  chunk_count: number;
  vector_count?: number | null;
  graph_entity_count?: number | null;
  graph_relation_count?: number | null;
  retention_policy?: Record<string, unknown>;
  privacy_boundary?: Record<string, unknown>;
};
export type DataVaultOverview = {
  workspace_id: string;
  tenant_id: string;
  documents: number;
  original_storage_bytes?: number | null;
  extracted_content_bytes: number;
  indexed_chunks: number;
  vector_embeddings?: number | null;
  ocr_pages: number;
  graph_entities?: number | null;
  graph_relationships?: number | null;
  chats?: number | null;
  temporary_documents: number;
  privacy_mode: string;
  llm_provider_mode: string;
  embedding_provider_mode: string;
  storage_backend: string;
  pending_purges?: number;
  retention_expirations?: number;
  privacy_summary?: Record<string, number>;
  provider_summary?: Record<string, string[]>;
  documents_footprint: DataFootprintSummary[];
};
export type DataLineageStage = { stage: string; status: string; count?: number | null; bytes?: number | null; provider?: string | null; boundary?: string | null; details?: Record<string, unknown> };
export type DataLineage = { document_id: string; workspace_id: string; tenant_id: string; filename: string; stages: DataLineageStage[]; generated_at: string };
export type DeletionRequestRecord = { request_id: string; tenant_id: string; workspace_id: string; document_id: string; requested_by: string; reason: string; status: string; approved_by?: string | null; created_at: string; updated_at?: string | null };
export type PurgeJobRecord = {
  purge_job_id: string;
  workspace_id: string;
  document_id: string;
  status: string;
  reason: string;
  receipt: Record<string, unknown>;
  error?: string | null;
  created_at: string;
  updated_at?: string | null;
};
export type IndustryPack = {
  pack_id: string;
  label: string;
  objective_profile: string;
  query_mode: QueryMode;
  data_boundary: string;
  extraction_focus: string[];
  prompt_starters: string[];
};
export type IngestionJob = { job_id: string; filename: string; status: string; progress: number; message?: string; document_id?: string };
export type ApiKeyRecord = {
  key_id: string;
  name: string;
  masked_key: string;
  role: string;
  permissions: string[];
  revoked_at?: string | null;
  last_used_at?: string | null;
};

export type WorkspaceInvitation = {
  invitation_id: string;
  workspace_id: string;
  email: string;
  role: string;
  status: string;
  expires_at: string;
  created_at: string;
  invitation_token?: string | null;
};

export type Citation = {
  document_id?: string;
  filename: string;
  page_number: number;
  chunk_id: string;
  snippet: string;
  content_type?: string;
  preview_path?: string | null;
  bbox?: number[] | null;
};

export type VisualCard = {
  document_id?: string;
  title?: string;
  filename: string;
  page_number: number;
  visual_type: string;
  plain_language_explanation: string;
  preview_path?: string | null;
  bbox?: number[] | null;
};

export type AgentStep = { agent_name: string; action: string; output_summary?: string; status?: string };
export type AgentRun = { steps: AgentStep[] };
export type StreamStage = { stage: string; label: string; latency_ms?: number | null };

export type EvidenceCanvas = {
  summary?: string;
  citations?: Citation[];
  visual_cards?: VisualCard[];
  artifact_cards?: {
    artifact_id: string;
    artifact_type: string;
    title: string;
    page_number: number;
    filename: string;
    text?: string | string[];
    severity?: string;
    risk_tags?: string[];
  }[];
  agent_steps?: AgentStep[];
  confidence?: number;
  missing_evidence?: string[];
  why_this_answer?: string;
  graph_contribution?: Record<string, unknown> | null;
};

export type Message = {
  role: Role;
  text: string;
  evidenceCanvas?: EvidenceCanvas | null;
  agentRun?: AgentRun | null;
  stages?: StreamStage[];
  groundingStatus?: string;
};

export type QueryPayload = {
  question: string;
  workspace_id: string;
  language: string;
  response_language?: string;
  explanation_level: string;
  answer_mode: string;
  objective_profile: Objective;
  analysis_mode: string;
  query_mode: QueryMode;
  include_visual_evidence: boolean;
  return_evidence_canvas: boolean;
  mode: string;
  session_id: string;
};

export type QueryResponse = {
  answer: string;
  evidence_canvas?: EvidenceCanvas | null;
  agent_run?: AgentRun | null;
  confidence?: number;
  answer_language?: string;
  grounding_status?: string;
  verification?: Record<string, unknown>;
  agent_plan?: Record<string, unknown>;
  tool_trace?: Record<string, unknown>[];
  retrieval_metadata?: Record<string, unknown>;
};

export type ReadinessReport = {
  status: "ready" | "warning" | "blocked";
  blocker_count: number;
  warning_count: number;
  summary: string;
  checks: { name: string; status: "ok" | "warning" | "blocker"; message: string }[];
};

export type ObservabilitySnapshot = {
  components?: Record<string, any>;
  retrieval?: { cache_hit_rate?: number; avg_graph_selected_count?: number; blocked_answer_rate?: number };
  latency?: { p95_ms?: number; p99_ms?: number; avg_ms?: number };
  quality?: { citation_coverage?: number; failure_rate?: number; avg_confidence?: number };
};
