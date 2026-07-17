"""Ingestion pipeline: file -> text -> chunks -> embeddings + knowledge graph.

Documents are written into a single user's isolated namespace. The embedder,
chunker, OCR, and extractor are shared across all users; only the target stores
are user-specific.

    load ── chunk ── embed ── store vectors (user's namespace)
                        └──── extract entities/relations ── store graph ── link chunks
                                        └── resolve duplicate entities
                                        └── rebuild community summaries

Re-ingesting a source is an *update*: its previous chunks are deleted first, so
a shortened document can't leave stale tail chunks behind (chunk ids are
(doc, index)-stable, which without the delete makes old indexes immortal).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from graphrag.container import Container, Tenant
from graphrag.core.logging import get_logger
from graphrag.ingestion.enrich import build_communities, resolve_entities
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

            replaced = tenant.graph_store.delete_document(document.source)
            replaced += tenant.vector_store.delete_source(document.source)
            if replaced:
                log.info("reingest_replaced", source=document.source, removed=replaced)

            embeddings = c.embedder.embed_documents([ch.text for ch in chunks])
            for ch, vec in zip(chunks, embeddings, strict=True):
                ch.embedding = vec
            tenant.vector_store.upsert(chunks)
            if c.settings.storage.vector.provider != "neo4j":
                # Vectors live elsewhere, but fulltext search and MENTIONS
                # edges still need the chunk nodes in the graph.
                tenant.graph_store.upsert_chunks(chunks)

            if extract:
                self._build_graph(tenant, chunks, stats)

            stats.documents += 1
            stats.chunks += len(chunks)
            stats.files.append(document.source)
            log.info("ingested", user=tenant.user_id, source=document.source, chunks=len(chunks))

        if extract and stats.documents:
            self._enrich(tenant)
        return stats

    def _build_graph(self, tenant: Tenant, chunks, stats: IngestStats) -> None:
        # Extraction is one LLM call per chunk — by far the slowest part of
        # ingest — so those calls run concurrently. Writes stay serial:
        # concurrent MERGEs on the same entity keys only fight for locks.
        workers = max(1, self._c.settings.ingestion.max_concurrency)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            extracted = list(pool.map(self._c.extractor.extract, [c.text for c in chunks]))

        for chunk, (entities, relations) in zip(chunks, extracted, strict=True):
            if not entities:
                continue
            tenant.graph_store.add_entities(entities)
            tenant.graph_store.add_relations(relations)
            tenant.graph_store.link_chunk_entities(chunk.id, [e.key for e in entities])
            stats.entities += len(entities)
            stats.relations += len(relations)

    def _enrich(self, tenant: Tenant) -> None:
        cfg = self._c.settings.ingestion
        try:
            resolve_entities(tenant.graph_store, self._c.embedder, cfg.resolve_entities)
        except Exception as exc:  # enrichment must never fail the ingest
            log.warning("entity_resolution_failed", error=str(exc))
        try:
            build_communities(
                tenant.graph_store, self._c.embedder, self._c.extractor_llm,
                cfg.communities,
            )
        except Exception as exc:
            log.warning("community_build_failed", error=str(exc))
