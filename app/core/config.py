from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="Adaptive Multimodal RAG", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    cors_allowed_origins: str = Field(default="http://localhost:3000,http://127.0.0.1:3000", alias="CORS_ALLOWED_ORIGINS")

    qdrant_url: str = Field(default="http://qdrant:6333", alias="QDRANT_URL")
    qdrant_local_fallback_url: str = Field(default="file://./data/qdrant_local", alias="QDRANT_LOCAL_FALLBACK_URL")
    qdrant_collection: str = Field(default="aiwana_chunks_v2", alias="QDRANT_COLLECTION")

    database_backend: str = Field(default="postgres", alias="DATABASE_BACKEND")
    database_url: str = Field(default="postgresql+psycopg://aiwana:aiwana@postgres:5432/aiwana", alias="DATABASE_URL")
    sqlite_database_url: str = Field(default="sqlite:///./data/metadata.db", alias="SQLITE_DATABASE_URL")
    enable_sqlite_fallback: bool = Field(default=False, alias="ENABLE_SQLITE_FALLBACK")

    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    enable_redis: bool = Field(default=True, alias="ENABLE_REDIS")
    rate_limit_backend: str = Field(default="redis", alias="RATE_LIMIT_BACKEND")
    session_backend: str = Field(default="redis", alias="SESSION_BACKEND")
    agent_state_backend: str = Field(default="redis", alias="AGENT_STATE_BACKEND")
    cache_backend: str = Field(default="redis", alias="CACHE_BACKEND")

    object_storage_backend: str = Field(default="local", alias="OBJECT_STORAGE_BACKEND")
    object_storage_bucket: str = Field(default="aiwana-artifacts", alias="OBJECT_STORAGE_BUCKET")
    object_storage_local_dir: Path = Field(default=Path("./data/artifacts"), alias="OBJECT_STORAGE_LOCAL_DIR")
    object_storage_kms_key_id: str = Field(default="", alias="OBJECT_STORAGE_KMS_KEY_ID")
    object_storage_signed_url_expiry_seconds: int = Field(default=900, alias="OBJECT_STORAGE_SIGNED_URL_EXPIRY_SECONDS")
    object_storage_s3_lifecycle_documented: bool = Field(default=False, alias="OBJECT_STORAGE_S3_LIFECYCLE_DOCUMENTED")
    tenant_data_plane_mode: str = Field(default="shared", alias="TENANT_DATA_PLANE_MODE")
    enable_graph_memory: bool = Field(default=True, alias="ENABLE_GRAPH_MEMORY")
    graph_backend: str = Field(default="postgres", alias="GRAPH_BACKEND")
    enable_real_orchestrator: bool = Field(default=True, alias="ENABLE_REAL_ORCHESTRATOR")
    enable_queue_ingestion: bool = Field(default=False, alias="ENABLE_QUEUE_INGESTION")

    embedding_provider: str = Field(default="local_bge", alias="EMBEDDING_PROVIDER")
    embedding_model: str = Field(default="BAAI/bge-m3", alias="EMBEDDING_MODEL")
    embedding_model_path: Path = Field(default=Path("./models/bge-m3"), alias="EMBEDDING_MODEL_PATH")
    reranker_model: str = Field(default="BAAI/bge-reranker-v2-m3", alias="RERANKER_MODEL")
    reranker_model_path: Path = Field(default=Path("./models/bge-reranker-v2-m3"), alias="RERANKER_MODEL_PATH")
    embedding_batch_size: int = Field(default=32, alias="EMBEDDING_BATCH_SIZE")
    hf_home: str = Field(default="/models/huggingface", alias="HF_HOME")

    llm_provider: str = Field(default="groq", alias="LLM_PROVIDER")
    llm_model: str = Field(default="llama-3.3-70b-versatile", alias="LLM_MODEL")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    enable_openai_fallback: bool = Field(default=False, alias="ENABLE_OPENAI_FALLBACK")
    huggingface_provider_enabled: bool = Field(default=False, alias="HUGGINGFACE_PROVIDER_ENABLED")
    huggingface_model_cache: Path = Field(default=Path("./models/huggingface"), alias="HUGGINGFACE_MODEL_CACHE")
    huggingface_task_overrides: str = Field(default="", alias="HUGGINGFACE_TASK_OVERRIDES")
    huggingface_task_enables: str = Field(default="", alias="HUGGINGFACE_TASK_ENABLES")
    hf_embeddings_enabled: bool = Field(default=False, alias="HF_EMBEDDINGS_ENABLED")
    hf_reranking_enabled: bool = Field(default=False, alias="HF_RERANKING_ENABLED")
    hf_entity_extraction_enabled: bool = Field(default=False, alias="HF_ENTITY_EXTRACTION_ENABLED")
    hf_evidence_checking_enabled: bool = Field(default=False, alias="HF_EVIDENCE_CHECKING_ENABLED")
    hf_classification_enabled: bool = Field(default=False, alias="HF_CLASSIFICATION_ENABLED")
    hf_captioning_enabled: bool = Field(default=False, alias="HF_CAPTIONING_ENABLED")
    hf_ocr_vlm_enabled: bool = Field(default=False, alias="HF_OCR_VLM_ENABLED")
    huggingface_max_seconds: int = Field(default=30, alias="HUGGINGFACE_MAX_SECONDS")
    huggingface_max_memory_mb: int = Field(default=4096, alias="HUGGINGFACE_MAX_MEMORY_MB")

    enable_hybrid: bool = Field(default=True, alias="ENABLE_HYBRID")
    enable_reranker: bool = Field(default=True, alias="ENABLE_RERANKER")
    reranker_required: bool = Field(default=False, alias="RERANKER_REQUIRED")
    rerank_max_candidates: int = Field(default=20, alias="RERANK_MAX_CANDIDATES")
    rerank_batch_size: int = Field(default=16, alias="RERANK_BATCH_SIZE")
    rerank_timeout_seconds: float = Field(default=3.0, alias="RERANK_TIMEOUT_SECONDS")
    fast_retrieval_k: int = Field(default=24, alias="FAST_RETRIEVAL_K")
    fast_context_k: int = Field(default=6, alias="FAST_CONTEXT_K")
    balanced_retrieval_k: int = Field(default=30, alias="BALANCED_RETRIEVAL_K")
    balanced_rerank_k: int = Field(default=15, alias="BALANCED_RERANK_K")
    balanced_context_k: int = Field(default=8, alias="BALANCED_CONTEXT_K")
    deep_retrieval_k: int = Field(default=60, alias="DEEP_RETRIEVAL_K")
    deep_rerank_k: int = Field(default=30, alias="DEEP_RERANK_K")
    deep_context_k: int = Field(default=12, alias="DEEP_CONTEXT_K")
    enable_router: bool = Field(default=True, alias="ENABLE_ROUTER")
    enable_multimodal: bool = Field(default=True, alias="ENABLE_MULTIMODAL")
    enable_graph: bool = Field(default=False, alias="ENABLE_GRAPH")
    enable_named_vectors: bool = Field(default=True, alias="ENABLE_NAMED_VECTORS")
    enable_bge_m3_sparse: bool = Field(default=False, alias="ENABLE_BGE_M3_SPARSE")
    enable_persistent_memory: bool = Field(default=True, alias="ENABLE_PERSISTENT_MEMORY")
    enable_rate_limit: bool = Field(default=True, alias="ENABLE_RATE_LIMIT")
    enable_security_headers: bool = Field(default=True, alias="ENABLE_SECURITY_HEADERS")
    require_auth: bool = Field(default=True, alias="REQUIRE_AUTH")
    enable_local_user_fallback: bool = Field(default=False, alias="ENABLE_LOCAL_USER_FALLBACK")
    auth_secret: str = Field(default="", alias="AUTH_SECRET")
    access_token_ttl_minutes: int = Field(default=60, alias="ACCESS_TOKEN_TTL_MINUTES")
    session_ttl_hours: int = Field(default=12, alias="SESSION_TTL_HOURS")
    auth_cookie_secure: bool = Field(default=True, alias="AUTH_COOKIE_SECURE")
    google_client_id: str = Field(default="", alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(default="http://localhost:8000/auth/google/callback", alias="GOOGLE_REDIRECT_URI")
    invitation_ttl_hours: int = Field(default=168, alias="INVITATION_TTL_HOURS")
    email_provider: str = Field(default="console", alias="EMAIL_PROVIDER")
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")

    max_upload_files: int = Field(default=8, alias="MAX_UPLOAD_FILES")
    max_upload_mb: int = Field(default=80, alias="MAX_UPLOAD_MB")
    max_workspace_documents: int = Field(default=50, alias="MAX_WORKSPACE_DOCUMENTS")
    max_pasted_text_chars: int = Field(default=500_000, alias="MAX_PASTED_TEXT_CHARS")
    rate_limit_requests: int = Field(default=120, alias="RATE_LIMIT_REQUESTS")
    rate_limit_window_seconds: int = Field(default=60, alias="RATE_LIMIT_WINDOW_SECONDS")

    chunk_size: int = Field(default=800, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=120, alias="CHUNK_OVERLAP")
    dense_weight: float = Field(default=0.7, alias="DENSE_WEIGHT")
    sparse_weight: float = Field(default=0.3, alias="SPARSE_WEIGHT")
    default_top_k: int = Field(default=5, alias="DEFAULT_TOP_K")
    retrieval_candidate_pool: int = Field(default=12, alias="RETRIEVAL_CANDIDATE_POOL")
    max_context_chunks: int = Field(default=6, alias="MAX_CONTEXT_CHUNKS")
    min_confidence_to_answer: float = Field(default=0.42, alias="MIN_CONFIDENCE_TO_ANSWER")
    session_memory_turns: int = Field(default=6, alias="SESSION_MEMORY_TURNS")
    retrieval_cache_ttl_seconds: int = Field(default=600, alias="RETRIEVAL_CACHE_TTL_SECONDS")
    retrieval_cache_bypass: bool = Field(default=False, alias="RETRIEVAL_CACHE_BYPASS")
    graph_eval_min_lift: float = Field(default=0.05, alias="GRAPH_EVAL_MIN_LIFT")
    graph_eval_required: bool = Field(default=True, alias="GRAPH_EVAL_REQUIRED")
    smoke_strict: bool = Field(default=False, alias="AIWANA_SMOKE_STRICT")
    qdrant_tenant_mode: str = Field(default="shared_collection", alias="QDRANT_TENANT_MODE")
    signed_url_expiry_seconds: int = Field(default=300, alias="SIGNED_URL_EXPIRY_SECONDS")
    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    ollama_base_url: str = Field(default="http://ollama:11434", alias="OLLAMA_BASE_URL")
    llm_privacy_mode: str = Field(default="external_allowed", alias="LLM_PRIVACY_MODE")
    chat_retention_days: int = Field(default=90, alias="CHAT_RETENTION_DAYS")
    query_log_retention_days: int = Field(default=90, alias="QUERY_LOG_RETENTION_DAYS")
    audit_retention_days: int = Field(default=365, alias="AUDIT_RETENTION_DAYS")
    deleted_document_retention_days: int = Field(default=30, alias="DELETED_DOCUMENT_RETENTION_DAYS")

    data_dir: Path = Field(default=Path("./data"), alias="DATA_DIR")
    upload_dir: Path = Field(default=Path("./data/uploads"), alias="UPLOAD_DIR")
    log_dir: Path = Field(default=Path("./data/logs"), alias="LOG_DIR")
    metadata_db: Path = Field(default=Path("./data/metadata.db"), alias="METADATA_DB")
    backup_dir: Path = Field(default=Path("./data/backups"), alias="BACKUP_DIR")

    def model_post_init(self, __context) -> None:
        if self.data_dir != Path("./data") and self.backup_dir == Path("./data/backups"):
            self.backup_dir = self.data_dir / "backups"

    @property
    def supported_llm_providers(self) -> set[str]:
        return {"groq", "openai", "openai_compatible", "ollama", "private"}

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    settings.metadata_db.parent.mkdir(parents=True, exist_ok=True)
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    settings.object_storage_local_dir.mkdir(parents=True, exist_ok=True)
    return settings
