"""Request/response models for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from graphrag.core.types import RetrievedChunk


class Source(BaseModel):
    chunk_id: str
    source: str
    snippet: str
    score: float
    retriever: str

    @classmethod
    def from_chunk(cls, c: RetrievedChunk) -> Source:
        snippet = c.text if len(c.text) <= 400 else c.text[:400] + "…"
        return cls(
            chunk_id=c.chunk_id, source=c.source, snippet=snippet,
            score=round(c.score, 4), retriever=c.retriever,
        )


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    style: str = Field("detailed", description="concise | detailed | technical | eli5")
    thread_id: str = Field("default", description="conversation id for multi-turn memory")
    # None -> the server default (api.stream in config) decides.
    stream: bool | None = None
    # Chat model id from the allowed list; unknown ids fall back to the default.
    model: str | None = None


class ToolCall(BaseModel):
    tool: str
    args: dict = {}


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source] = []
    tool_calls: list[ToolCall] = []


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    k: int = 8


class SearchResponse(BaseModel):
    results: list[Source] = []


class CompareRequest(BaseModel):
    subjects: list[str] = Field(..., min_length=2)
    aspects: list[str] = []
    style: str = "detailed"
    thread_id: str = "default"
    model: str | None = None


class IngestResponse(BaseModel):
    job_id: str
    status: str


class IngestStatus(BaseModel):
    job_id: str
    status: str  # queued | running | done | error
    detail: str = ""
    documents: int = 0
    chunks: int = 0
    entities: int = 0
    relations: int = 0


class StoredFile(BaseModel):
    file_id: str
    name: str
    source: str


class FileList(BaseModel):
    files: list[StoredFile] = []
    used: int = 0
    limit: int = 0


class DeleteResponse(BaseModel):
    file_id: str
    chunks_removed: int = 0


class SignupRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)


class VerifyRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    code: str = Field(..., min_length=4, max_length=12)


class EmailRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)


class Acknowledged(BaseModel):
    ok: bool = True
    message: str = ""


class ModelOption(BaseModel):
    model: str
    label: str
    provider: str


class Me(BaseModel):
    """Everything the UI needs to render a signed-in session."""

    user_id: str
    email: str = ""
    role: str = "user"
    tenant_id: str = ""
    authenticated: bool = True
    models: list[ModelOption] = []
    default_model: str = ""


class APIKeyInfo(BaseModel):
    id: int
    label: str = ""
    created_at: str = ""
    last_used_at: str | None = None


class APIKeyList(BaseModel):
    keys: list[APIKeyInfo] = []


class APIKeyCreate(BaseModel):
    label: str = Field("", max_length=64)


class APIKeyCreated(BaseModel):
    id: int
    api_key: str  # shown once


class ThreadInfo(BaseModel):
    id: str
    title: str
    created_at: str = ""
    updated_at: str = ""


class ThreadList(BaseModel):
    threads: list[ThreadInfo] = []


class ThreadCreate(BaseModel):
    title: str = Field("New chat", max_length=120)


class ThreadUpdate(BaseModel):
    title: str | None = Field(None, max_length=120)


class MessageInfo(BaseModel):
    id: int
    role: str
    content: str
    sources: list = []
    model: str = ""
    created_at: str = ""


class ThreadMessages(BaseModel):
    thread: ThreadInfo
    messages: list[MessageInfo] = []


class LimitsInfo(BaseModel):
    """A user's allowances and what they've used, for the account page."""

    limits: dict[str, int] = {}
    usage: dict[str, int] = {}
    files_used: int = 0
    storage_used_mb: float = 0.0
    threads_used: int = 0


class UserCreate(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=48)


class UserInfo(BaseModel):
    user_id: str


class UserCreated(BaseModel):
    user_id: str
    api_key: str | None = None  # returned once; only when auth is enabled


class UsersList(BaseModel):
    users: list[str] = []


class KeysRevoked(BaseModel):
    user_id: str
    revoked: int


class UsageReport(BaseModel):
    # user id -> streamed answer tokens (approximate; counted per SSE chunk)
    tokens: dict[str, int] = {}


class Health(BaseModel):
    status: str
    version: str


class Ready(BaseModel):
    ready: bool
    neo4j: bool
    redis: bool
