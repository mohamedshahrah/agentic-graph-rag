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
