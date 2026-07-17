"""Graph store interface — the knowledge graph half of the store."""

from __future__ import annotations

import abc

from graphrag.core.types import Chunk, Entity, Relation, RetrievedChunk


class GraphStore(abc.ABC):
    @abc.abstractmethod
    def setup(self) -> None:
        """Create constraints / full-text indexes (idempotent)."""

    @abc.abstractmethod
    def add_entities(self, entities: list[Entity]) -> None: ...

    @abc.abstractmethod
    def add_relations(self, relations: list[Relation]) -> None: ...

    @abc.abstractmethod
    def upsert_chunks(self, chunks: list[Chunk]) -> None:
        """Create/refresh chunk nodes *without* embeddings — needed when the
        vector store is external but fulltext + MENTIONS still live here."""

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

    @abc.abstractmethod
    def expand_chunks(
        self, entity_names: list[str], hops: int = 2, limit: int = 12
    ) -> list[RetrievedChunk]:
        """Chunks mentioning the seeds or their neighborhood, scored by graph
        distance — the traversal behind graph-augmented retrieval."""

    # -- entity resolution ----------------------------------------------------
    @abc.abstractmethod
    def all_entities(self, limit: int = 5000) -> list[dict]: ...

    @abc.abstractmethod
    def merge_entities(self, winner_key: str, loser_keys: list[str]) -> None: ...

    # -- communities (global search) ------------------------------------------
    @abc.abstractmethod
    def entity_edges(self, limit: int = 20000) -> list[tuple[str, str]]: ...

    @abc.abstractmethod
    def replace_communities(self, communities: list[dict]) -> None: ...

    @abc.abstractmethod
    def communities(self) -> list[dict]: ...
