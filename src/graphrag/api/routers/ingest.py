"""Add documents to a user's knowledge base.

Ingestion runs as a background task so a large upload never blocks the request.
Where it runs depends on deployment: with GRAPHRAG_USE_WORKER it goes to an Arq
worker in a separately resource-limited container; otherwise it runs in-process,
which is what the duckdb vector provider requires (one process must own each
tenant's database file). Status is persisted in Redis and polled by job id. All
ingestion is scoped to the current user."""

from __future__ import annotations

import asyncio
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile

from graphrag.api.deps import AuthUser, get_container, get_current_user, get_job_store
from graphrag.api.schemas import (
    DeleteResponse,
    FileList,
    IngestResponse,
    IngestStatus,
    StoredFile,
)
from graphrag.container import Container
from graphrag.core.logging import get_logger
from graphrag.jobs import JobStatus, JobStore
from graphrag.pipelines import IngestPipeline

router = APIRouter(tags=["ingest"])
log = get_logger(__name__)

# Server-side ingest is confined to this tree. Without the fence, any caller
# could ingest an arbitrary server file (.env included) and read it back
# through /search.
_DATA_ROOT = Path("data")
_UPLOAD_DIR = _DATA_ROOT / "uploads"
_DOWNLOAD_DIR = _DATA_ROOT / "downloads"

_URL_SUFFIX = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "text/csv": ".csv",
}


# Only one ingest at a time in-process. Extraction fires a burst of concurrent
# LLM calls per document; two documents at once would double that against the
# same two vCPUs the chat stream is using. Queued jobs simply wait, and the
# client already polls for status.
_INGEST_SLOT = asyncio.Semaphore(1)


def _inproc_ingest(container: Container, store: JobStore, job_id: str, path: str, user_id) -> None:
    """Run the pipeline and record the outcome. Blocking — call it off the loop."""
    store.set(JobStatus(job_id, status="running"))
    try:
        stats = IngestPipeline(container).run(path, user_id=user_id)
        store.set(
            JobStatus(job_id, status="done", documents=stats.documents, chunks=stats.chunks,
                      entities=stats.entities, relations=stats.relations)
        )
    except Exception as exc:
        log.warning("ingest_job_failed", job=job_id, error=str(exc))
        store.set(JobStatus(job_id, status="error", detail=str(exc)))


async def _run_ingest(container: Container, store: JobStore, job_id: str, path: str, user_id):
    """One queued ingest, off the event loop so streaming stays responsive."""
    async with _INGEST_SLOT:
        await asyncio.to_thread(_inproc_ingest, container, store, job_id, path, user_id)


async def _enqueue(
    request: Request, background: BackgroundTasks, container: Container,
    store: JobStore, path: str, user_id,
) -> IngestResponse:
    job_id = uuid.uuid4().hex[:12]
    store.set(JobStatus(job_id, status="queued"))
    arq = getattr(request.app.state, "arq", None)
    if arq is not None:
        await arq.enqueue_job("ingest_task", job_id, path, user_id)
    else:  # no worker -> run in this process
        background.add_task(_run_ingest, container, store, job_id, path, user_id)
    return IngestResponse(job_id=job_id, status="queued")


def _files_key(user: str) -> str:
    return f"files:{user}"


# Reserve atomically: HSET then check, undoing the write if it broke the cap.
# Two requests racing must not both slip past the limit, which is why this is a
# script rather than a read-then-write.
_RESERVE = """
redis.call('HSET', KEYS[1], ARGV[1], ARGV[2])
if redis.call('HLEN', KEYS[1]) > tonumber(ARGV[3]) then
  redis.call('HDEL', KEYS[1], ARGV[1])
  return 0
end
return 1
"""


def _reserve_file_slot(
    container: Container, user: str, limit: int, file_id: str, path: str
) -> bool:
    """Claim a slot for `file_id`, tracking the file so the slot can be given back.

    A plain counter would only ever go up: a failed ingest or a deleted file
    would burn a slot for good, and at the cap the user is locked out with no
    way back. Holding the actual files means the count reflects what exists.
    """
    r = container.redis
    if r is None:
        return True  # cannot enforce a cross-request cap without Redis
    return bool(r.eval(_RESERVE, 1, _files_key(user), file_id, path, limit))


def _release_file_slot(container: Container, user: str, file_id: str) -> None:
    r = container.redis
    if r is not None:
        r.hdel(_files_key(user), file_id)


@router.post("/ingest/upload", response_model=IngestResponse)
async def ingest_upload(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile,
    container: Container = Depends(get_container),
    store: JobStore = Depends(get_job_store),
    user: AuthUser = Depends(get_current_user),
) -> IngestResponse:
    api = container.settings.api
    user_key = user.tenant_id

    data = await file.read()
    if len(data) > api.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {api.max_upload_mb} MB limit")

    file_id = uuid.uuid4().hex[:8]
    dest = _UPLOAD_DIR / (file_id + "_" + Path(file.filename or "upload").name)
    if not _reserve_file_slot(container, user_key, api.max_files_per_user, file_id, str(dest)):
        raise HTTPException(
            status_code=429,
            detail=(
                f"File limit reached ({api.max_files_per_user} per user). "
                "Delete a file to free a slot."
            ),
        )

    try:
        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    except OSError:
        _release_file_slot(container, user_key, file_id)  # don't strand the slot
        raise
    return await _enqueue(request, background, container, store, str(dest), user_key)


@router.get("/ingest/files", response_model=FileList)
def list_files(
    container: Container = Depends(get_container),
    user: AuthUser = Depends(get_current_user),
) -> FileList:
    user_key = user.tenant_id
    limit = container.settings.api.max_files_per_user
    r = container.redis
    if r is None:
        return FileList(files=[], used=0, limit=limit)
    stored = r.hgetall(_files_key(user_key))
    files = [
        StoredFile(file_id=fid, name=Path(path).name, source=path)
        for fid, path in stored.items()
    ]
    return FileList(files=sorted(files, key=lambda f: f.name), used=len(files), limit=limit)


@router.delete("/ingest/files/{file_id}", response_model=DeleteResponse)
def delete_file(
    file_id: str,
    container: Container = Depends(get_container),
    user: AuthUser = Depends(get_current_user),
) -> DeleteResponse:
    """Remove an uploaded file, everything it put in the graph, and its slot."""
    user_key = user.tenant_id
    r = container.redis
    if r is None:
        raise HTTPException(status_code=503, detail="File tracking needs Redis")

    # Look the path up in *this* user's set, so a file_id can't reach another
    # tenant's document.
    source = r.hget(_files_key(user_key), file_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"No such file: {file_id}")

    tenant = container.tenant(user_key)
    removed = tenant.graph_store.delete_document(source)
    removed += tenant.vector_store.delete_source(source)  # no-op for Neo4j vectors
    Path(source).unlink(missing_ok=True)
    _release_file_slot(container, user_key, file_id)
    log.info("file_deleted", user=user_key, file=file_id, chunks=removed)
    return DeleteResponse(file_id=file_id, chunks_removed=removed)


def _fetch_url(url: str, max_bytes: int) -> Path:
    """Download a document into data/downloads with a size cap."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only http(s) URLs can be ingested")
    req = urllib.request.Request(url, headers={"User-Agent": "graphrag-ingest"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — scheme checked
            data = resp.read(max_bytes + 1)
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not fetch URL: {exc}") from exc
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="Remote document exceeds the upload limit")

    name = Path(parsed.path).name or "download"
    if not Path(name).suffix:
        name += _URL_SUFFIX.get(ctype, ".html" if "html" in ctype else ".txt")
    dest = _DOWNLOAD_DIR / (uuid.uuid4().hex[:8] + "_" + name)
    _DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


@router.post("/ingest", response_model=IngestResponse)
async def ingest_path(
    request: Request,
    background: BackgroundTasks,
    path: str,
    container: Container = Depends(get_container),
    store: JobStore = Depends(get_job_store),
    user: AuthUser = Depends(get_current_user),
) -> IngestResponse:
    """Ingest a server-side path under `data/`, or an http(s) URL."""
    if path.startswith(("http://", "https://")):
        max_bytes = container.settings.api.max_upload_mb * 1024 * 1024
        dest = _fetch_url(path, max_bytes)
        return await _enqueue(
            request, background, container, store, str(dest), user.tenant_id
        )

    requested = Path(path)
    try:
        resolved = requested.resolve()
        resolved.relative_to(_DATA_ROOT.resolve())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Server-side ingest is restricted to {_DATA_ROOT}/ "
                   "(upload the file, or pass an http(s) URL)",
        ) from None
    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")
    return await _enqueue(
        request, background, container, store, str(resolved), user.tenant_id
    )


@router.get("/ingest/{job_id}", response_model=IngestStatus)
def ingest_status(job_id: str, store: JobStore = Depends(get_job_store)) -> IngestStatus:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return IngestStatus(**job.to_dict())
