"""Typed configuration models.

`Settings` mirrors the YAML files (see `configs/`). `Secrets` reads API keys and
service URLs from the environment (`.env`), keeping credentials out of the YAML.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppCfg(BaseModel):
    name: str = "agentic-graph-rag"
    log_level: str = "INFO"
    corpus: str = "default"


class LLMCfg(BaseModel):
    provider: str = "ollama"
    model: str = "qwen2.5:7b-instruct"
    temperature: float = 0.1
    max_tokens: int = 2048
    extra: dict = Field(default_factory=dict)


class EmbeddingCacheCfg(BaseModel):
    enabled: bool = True
    ttl_seconds: int = 604800


class EmbeddingCfg(BaseModel):
    provider: str = "sentence_transformers"
    model: str = "BAAI/bge-m3"
    # HF tokenizer used to measure chunk sizes. Defaults to `model`, which is
    # correct when that's an HF repo id. Name it explicitly when it isn't — an
    # Ollama tag like `bge-m3:latest` can't be resolved, and chunking silently
    # falls back to a word-count heuristic that undercounts by ~15%. Only the
    # tokenizer is fetched (~17 MB), never the weights.
    tokenizer: str | None = None
    dimensions: int | None = None
    device: str = "auto"
    batch_size: int = 32
    normalize: bool = True
    max_seq_length: int = 512
    query_prefix: str = ""
    document_prefix: str = ""
    pooling: str = "mean"
    cache: EmbeddingCacheCfg = Field(default_factory=EmbeddingCacheCfg)


class SemanticChunkCfg(BaseModel):
    threshold: float = 0.75
    min_chunk_tokens: int = 96


class ChunkingCfg(BaseModel):
    strategy: str = "recursive"
    max_tokens: int = 384
    overlap: int = 64
    semantic: SemanticChunkCfg = Field(default_factory=SemanticChunkCfg)


class VisionLLMCfg(BaseModel):
    provider: str = "ollama"
    model: str = "gemma4:e4b"
    prompt: str = (
        "Transcribe all text in this image exactly, preserving structure. "
        "Output only the text."
    )


class TesseractCfg(BaseModel):
    lang: str = "eng"


class OCRCfg(BaseModel):
    enabled: bool = True
    engine: str = "vision_llm"
    # A scanned page usually still carries a thin text layer — a page number, a
    # header stamped by the scanner — so "extracted some text" does not mean
    # "read the page". Pages whose text layer is shorter than this are treated
    # as images and sent to OCR. Set 0 to only OCR pages that extract nothing at
    # all (which misses any scan bearing a page label).
    min_text_chars: int = 100
    vision_llm: VisionLLMCfg = Field(default_factory=VisionLLMCfg)
    tesseract: TesseractCfg = Field(default_factory=TesseractCfg)


class GraphStoreCfg(BaseModel):
    provider: str = "neo4j"
    database: str = "neo4j"


class VectorStoreCfg(BaseModel):
    provider: str = "neo4j"
    index_name: str = "chunk_embeddings"
    similarity: str = "cosine"


class StorageCfg(BaseModel):
    graph: GraphStoreCfg = Field(default_factory=GraphStoreCfg)
    vector: VectorStoreCfg = Field(default_factory=VectorStoreCfg)


class RerankCfg(BaseModel):
    enabled: bool = True
    provider: str = "cross_encoder"
    model: str = "BAAI/bge-reranker-v2-m3"
    # --- generative rerank only (provider = ollama | anthropic | openai | gemini) ---
    # One LLM call per candidate, so cost scales with retrieval.candidate_k.
    concurrency: int = 4
    max_tokens: int = 16
    prompt: str = (
        "Rate how well the document answers the query, from 0 to 10.\n"
        "Reply with only the number.\n\n"
        "Query: {query}\n\nDocument: {document}"
    )
    extra: dict = Field(default_factory=dict)  # provider kwargs, e.g. {reasoning: true}


class RetrievalCfg(BaseModel):
    top_k: int = 8
    candidate_k: int = 24
    graph_hops: int = 2
    rerank: RerankCfg = Field(default_factory=RerankCfg)


class AgentCfg(BaseModel):
    memory: bool = True
    max_tool_iterations: int = 6
    default_style: str = "detailed"


class IngestionCfg(BaseModel):
    extract_graph: bool = True
    max_concurrency: int = 4
    # Model used to pull entities/relations out of each chunk. Defaults to the
    # top-level `llm` when unset. Worth splitting out: extraction sees one chunk
    # at a time, so it needs far less context than chat — and on a small GPU the
    # context size is what decides whether the model fits in VRAM at all.
    llm: LLMCfg | None = None


class AuthCfg(BaseModel):
    # When enabled, requests must carry a valid API key (Authorization: Bearer
    # <key>, or X-API-Key). The verified key determines the user — the
    # X-User-Id header is then ignored. Disabled by default for local dev.
    enabled: bool = False


class TenancyCfg(BaseModel):
    # Each user gets an isolated namespace. The heavy models are shared across
    # all users (loaded once) — only the lightweight store/retriever wrappers are
    # per-user, which is what keeps memory flat as users grow.
    enabled: bool = True
    default_user: str = "default"
    # False -> isolate by a `corpus` tag inside one Neo4j database (Community-safe).
    # True  -> a real Neo4j database per user (requires Neo4j Enterprise).
    per_tenant_database: bool = False
    database_prefix: str = "u_"
    # Bound the in-memory tenant cache. Evicting a tenant drops only cheap
    # wrappers; the shared models stay resident.
    max_active_tenants: int = 256


class APICfg(BaseModel):
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    cors_methods: list[str] = Field(default_factory=lambda: ["GET", "POST", "OPTIONS"])
    cors_headers: list[str] = Field(
        default_factory=lambda: ["Content-Type", "X-User-Id", "Authorization"]
    )
    stream: bool = True
    rate_limit: str = "60/minute"      # per user (falls back to client IP)
    max_upload_mb: int = 25            # reject uploads larger than this
    max_files_per_user: int = 10       # cap uploaded files per user


class Settings(BaseModel):
    """The fully-resolved, non-secret configuration."""

    app: AppCfg = Field(default_factory=AppCfg)
    llm: LLMCfg = Field(default_factory=LLMCfg)
    embeddings: EmbeddingCfg = Field(default_factory=EmbeddingCfg)
    chunking: ChunkingCfg = Field(default_factory=ChunkingCfg)
    ocr: OCRCfg = Field(default_factory=OCRCfg)
    storage: StorageCfg = Field(default_factory=StorageCfg)
    retrieval: RetrievalCfg = Field(default_factory=RetrievalCfg)
    agent: AgentCfg = Field(default_factory=AgentCfg)
    ingestion: IngestionCfg = Field(default_factory=IngestionCfg)
    tenancy: TenancyCfg = Field(default_factory=TenancyCfg)
    auth: AuthCfg = Field(default_factory=AuthCfg)
    api: APICfg = Field(default_factory=APICfg)


class Secrets(BaseSettings):
    """Credentials & service URLs, read from the environment / `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    profile: str = Field(default="api", alias="GRAPHRAG_PROFILE")

    # Where the YAML profiles live. Only needed when the package is installed
    # away from the repo (the Docker image sets it to /app/configs); a source
    # checkout finds `configs/` on its own.
    config_dir: Path | None = Field(default=None, alias="GRAPHRAG_CONFIG_DIR")

    neo4j_uri: str = Field(default="bolt://localhost:7687", alias="GRAPHRAG_NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", alias="GRAPHRAG_NEO4J_USER")
    neo4j_password: str = Field(default="please-change-me", alias="GRAPHRAG_NEO4J_PASSWORD")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="GRAPHRAG_REDIS_URL")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="GRAPHRAG_OLLAMA_BASE_URL")

    # Optional admin key: when set (and auth enabled), required to create users.
    admin_api_key: str | None = Field(default=None, alias="GRAPHRAG_ADMIN_KEY")

    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    google_api_key: str | None = Field(default=None, alias="GOOGLE_API_KEY")
    voyage_api_key: str | None = Field(default=None, alias="VOYAGE_API_KEY")
    cohere_api_key: str | None = Field(default=None, alias="COHERE_API_KEY")
