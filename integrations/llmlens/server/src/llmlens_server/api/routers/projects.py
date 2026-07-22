"""Project + API-key management (admin-gated). Creating a project mints a secret
key, shown once, that apps use to authenticate ingestion."""

from __future__ import annotations

import re
import secrets as pysecrets

from fastapi import APIRouter, Depends

from llmlens_server.api.deps import get_pg, require_admin
from llmlens_server.api.schemas import ProjectCreate, ProjectCreated
from llmlens_server.core.keys import generate_key, hash_key
from llmlens_server.storage.postgres import repos

router = APIRouter(tags=["projects"])


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "project"
    return f"{base}-{pysecrets.token_hex(3)}"


@router.post("/api/projects", response_model=ProjectCreated)
def create_project(
    payload: ProjectCreate,
    _: None = Depends(require_admin),
    pg=Depends(get_pg),
) -> ProjectCreated:
    project_id = _slug(payload.name)
    repos.create_project(pg, project_id, payload.name)
    secret = generate_key("sk")
    repos.add_api_key(pg, project_id, hash_key(secret), kind="secret")
    return ProjectCreated(id=project_id, name=payload.name, secret_key=secret)


@router.get("/api/projects")
def list_projects(_: None = Depends(require_admin), pg=Depends(get_pg)) -> dict:
    return {"projects": repos.list_projects(pg)}
