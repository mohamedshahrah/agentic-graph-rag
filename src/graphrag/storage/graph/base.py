"""Graph store interface — the knowledge graph half of the store."""

from __future__ import annotations

import abc

from graphrag.core.types import Entity, Relation, RetrievedChunk


class GraphStore(abc.ABC):
    @abc.abstractmethod
    def setup(self) -> None:
        """Create constraints / full-text indexes (idempotent)."""

    @abc.abstractmethod
    def add_entities(self, entities: list[Entity]) -> None: ...

    @abc.abstractmethod
    def add_relations(self, relations: list[Relation]) -> None: ...

    @abc.abstractmethod
    def link_chunk_entities(self, chunk_id: str, entity_keys: list[str]) -> None: ...

    @abc.abstractmethod
    def delete_document(self, source: str) -> int:
        """Drop everything ingested from `source` and return the chunks removed.

        Entities left mentioned by no chunk are removed too — they only exist as
        evidence from some document, so an orphan is dead weight in retrieval.
        """

    @abc.abstractmethod
    def neighbors(self, entity_name: str, hops: int = 2) -> str:
        """Return a human-readable list of relations around an entity."""

    @abc.abstractmethod
    def get_entity(self, name: str) -> dict: ...

    @abc.abstractmethod
    def fulltext_entities(self, query: str, k: int = 5) -> list[str]: ...

    @abc.abstractmethod
    def fulltext_chunks(self, query: str, k: int = 8) -> list[RetrievedChunk]: ...

    @abc.abstractmethod
    def chunks_for_entities(
        self, entity_names: list[str], limit: int = 12
    ) -> list[RetrievedChunk]: ...
