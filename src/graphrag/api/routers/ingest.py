"""Add documents to a user's knowledge base.

Ingestion is queued to a background worker (Arq/Redis) so a large upload never
blocks the request and the heavy work runs in a separately resource-limited
container. If no queue is available, it falls back to an in-process task. Status
is persisted in Redis and polled by job id. All ingestion is scoped to the
current user (API key when auth is on, else the X-User-Id header)."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile

from graphrag.api.deps import get_container, get_current_user, get_job_store
from graphrag.api.schemas import (
    DeleteResponse,
    FileList,
    IngestResponse,
    IngestStatus,
    StoredFile,
)
from graphrag.container import Container, sanitize_user
from graphrag.core.logging import get_logger
from graphrag.jobs import JobStatus, JobStore
from graphrag.pipelines import IngestPipeline

router = APIRouter(tags=["ingest"])
log = get_logger(__name__)

_UPLOAD_DIR = Path("data/uploads")


def _inproc_ingest(container: Container, store: JobStore, job_id: str, path: str, user_id) -> None:
    """Fallback path when no queue worker is available."""
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


async def _enqueue(
    request: Request, background: BackgroundTasks, container: Container,
    store: JobStore, path: str, user_id,
) -> IngestResponse:
    job_id = uuid.uuid4().hex[:12]
    store.set(JobStatus(job_id, status="queued"))
    arq = getattr(request.app.state, "arq", None)
    if arq is not None:
        await arq.enqueue_job("ingest_task", job_id, path, user_id)
    else:  # no worker -> run in-process
        background.add_task(_inproc_ingest, container, store, job_id, path, user_id)
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
    user: str | None = Depends(get_current_user),
) -> IngestResponse:
    api = container.settings.api
    user_key = sanitize_user(user or container.settings.tenancy.default_user)

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
    return await _enqueue(request, background, container, store, str(dest), user)


@router.get("/ingest/files", response_model=FileList)
def list_files(
    container: Container = Depends(get_container),
    user: str | None = Depends(get_current_user),
) -> FileList:
    user_key = sanitize_user(user or container.settings.tenancy.default_user)
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
    user: str | None = Depends(get_current_user),
) -> DeleteResponse:
    """Remove an uploaded file, everything it put in the graph, and its slot."""
    user_key = sanitize_user(user or container.settings.tenancy.default_user)
    r = container.redis
    if r is None:
        raise HTTPException(status_code=503, detail="File tracking needs Redis")

    # Look the path up in *this* user's set, so a file_id can't reach another
    # tenant's document.
    source = r.hget(_files_key(user_key), file_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"No such file: {file_id}")

    removed = container.tenant(user_key).graph_store.delete_document(source)
    Path(source).unlink(missing_ok=True)
    _release_file_slot(container, user_key, file_id)
    log.info("file_deleted", user=user_key, file=file_id, chunks=removed)
    return DeleteResponse(file_id=file_id, chunks_removed=removed)


@router.post("/ingest", response_model=IngestResponse)
async def ingest_path(
    request: Request,
    background: BackgroundTasks,
    path: str,
    container: Container = Depends(get_container),
    store: JobStore = Depends(get_job_store),
    user: str | None = Depends(get_current_user),
) -> IngestResponse:
    if not Path(path).exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")
    return await _enqueue(request, background, container, store, path, user)


@router.get("/ingest/{job_id}", response_model=IngestStatus)
def ingest_status(job_id: str, store: JobStore = Depends(get_job_store)) -> IngestStatus:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return IngestStatus(**job.to_dict())
