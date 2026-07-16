"""Ingestion pipeline: file -> text -> chunks -> embeddings + knowledge graph.

Documents are written into a single user's isolated namespace. The embedder,
chunker, OCR, and extractor are shared across all users; only the target stores
are user-specific.

    load ── chunk ── embed ── store vectors (user's namespace)
                        └──── extract entities/relations ── store graph ── link chunks
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from graphrag.container import Container, Tenant
from graphrag.core.logging import get_logger
from graphrag.ingestion.loaders import iter_documents

log = get_logger(__name__)


@dataclass
class IngestStats:
    documents: int = 0
    chunks: int = 0
    entities: int = 0
    relations: int = 0
    files: list[str] = field(default_factory=list)


class IngestPipeline:
    def __init__(self, container: Container) -> None:
        self._c = container

    def run(self, path: str | Path, user_id: str | None = None) -> IngestStats:
        c = self._c
        tenant = c.tenant(user_id)  # resolves + prepares the user's namespace
        stats = IngestStats()
        extract = c.settings.ingestion.extract_graph

        for document in iter_documents(
            path, ocr=c.ocr, min_text_chars=c.settings.ocr.min_text_chars
        ):
            if not document.content.strip():
                log.warning("empty_document", source=document.source)
                continue

            chunks = c.chunker.chunk(document)
            if not chunks:
                continue

            embeddings = c.embedder.embed_documents([ch.text for ch in chunks])
            for ch, vec in zip(chunks, embeddings, strict=True):
                ch.embedding = vec
            tenant.vector_store.upsert(chunks)

            if extract:
                self._build_graph(tenant, chunks, stats)

            stats.documents += 1
            stats.chunks += len(chunks)
            stats.files.append(document.source)
            log.info("ingested", user=tenant.user_id, source=document.source, chunks=len(chunks))

        return stats

    def _build_graph(self, tenant: Tenant, chunks, stats: IngestStats) -> None:
        for chunk in chunks:
            entities, relations = self._c.extractor.extract(chunk.text)
            if not entities:
                continue
            tenant.graph_store.add_entities(entities)
            tenant.graph_store.add_relations(relations)
            tenant.graph_store.link_chunk_entities(chunk.id, [e.key for e in entities])
            stats.entities += len(entities)
            stats.relations += len(relations)
