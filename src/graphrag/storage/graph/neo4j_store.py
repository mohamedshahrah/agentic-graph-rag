"""Neo4j-backed knowledge graph. Entities are :Entity nodes, relations are typed
edges (created via APOC), and chunks link to the entities they mention."""

from __future__ import annotations

from graphrag.core.types import Entity, Relation, RetrievedChunk
from graphrag.storage.graph.base import GraphStore


class Neo4jGraphStore(GraphStore):
    def __init__(self, driver, database: str, corpus: str) -> None:
        self._driver = driver
        self._db = database
        self._corpus = corpus

    def _run(self, query: str, **params):
        with self._driver.session(database=self._db) as session:
            return list(session.run(query, corpus=self._corpus, **params))

    # -- schema ---------------------------------------------------------------
    def setup(self) -> None:
        stmts = [
            "CREATE CONSTRAINT entity_key IF NOT EXISTS "
            "FOR (e:Entity) REQUIRE e.key IS UNIQUE",
            "CREATE CONSTRAINT chunk_id IF NOT EXISTS "
            "FOR (c:Chunk) REQUIRE c.id IS UNIQUE",
            "CREATE FULLTEXT INDEX chunk_fulltext IF NOT EXISTS "
            "FOR (c:Chunk) ON EACH [c.text]",
            "CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS "
            "FOR (e:Entity) ON EACH [e.name, e.description]",
        ]
        with self._driver.session(database=self._db) as session:
            for stmt in stmts:
                session.run(stmt)

    # -- writes ---------------------------------------------------------------
    def add_entities(self, entities: list[Entity]) -> None:
        rows = [
            {"key": e.key, "name": e.name, "type": e.type, "description": e.description}
            for e in entities
        ]
        self._run(
            """
            UNWIND $rows AS row
            MERGE (e:Entity {key: row.key})
            SET e.name = row.name, e.type = row.type, e.corpus = $corpus,
                e.description = CASE WHEN size(row.description) > size(coalesce(e.description,''))
                                     THEN row.description ELSE e.description END
            """,
            rows=rows,
        )

    def add_relations(self, relations: list[Relation]) -> None:
        rows = [
            {
                "s": r.source.strip().lower(),
                "t": r.target.strip().lower(),
                "type": r.type,
                "desc": r.description,
            }
            for r in relations
        ]
        try:
            self._run(
                # Two MATCHes with a WITH between them, not `MATCH (a), (b)`:
                # both are index seeks on the unique `key`, but the comma form
                # reads as a disconnected pattern and Neo4j logs a cartesian
                # product warning on every batch. Same plan, no noise.
                """
                UNWIND $rows AS row
                MATCH (a:Entity {key: row.s})
                WITH row, a
                MATCH (b:Entity {key: row.t})
                CALL apoc.merge.relationship(a, row.type, {}, {description: row.desc}, b, {})
                YIELD rel RETURN count(rel)
                """,
                rows=rows,
            )
        except Exception as exc:  # APOC missing -> generic typed edge fallback
            self._run(
                """
                UNWIND $rows AS row
                MATCH (a:Entity {key: row.s})
                WITH row, a
                MATCH (b:Entity {key: row.t})
                MERGE (a)-[r:RELATED_TO]->(b)
                SET r.type = row.type, r.description = row.desc
                """,
                rows=rows,
            )
            _ = exc

    def link_chunk_entities(self, chunk_id: str, entity_keys: list[str]) -> None:
        if not entity_keys:
            return
        self._run(
            """
            MATCH (c:Chunk {id: $chunk_id})
            UNWIND $keys AS key
            MATCH (e:Entity {key: key})
            MERGE (c)-[:MENTIONS]->(e)
            """,
            chunk_id=chunk_id,
            keys=entity_keys,
        )

    # -- reads (agent tools) --------------------------------------------------
    def delete_document(self, source: str) -> int:
        rows = self._run(
            """
            MATCH (c:Chunk {corpus: $corpus, source: $source})
            DETACH DELETE c
            RETURN count(c) AS removed
            """,
            source=source,
        )
        removed = rows[0]["removed"] if rows else 0
        # Entities are only ever evidence from a chunk; once nothing mentions
        # them they'd linger in graph expansion as dead weight.
        self._run(
            """
            MATCH (e:Entity {corpus: $corpus})
            WHERE NOT EXISTS { (:Chunk)-[:MENTIONS]->(e) }
            DETACH DELETE e
            """
        )
        return int(removed)

    def neighbors(self, entity_name: str, hops: int = 2) -> str:
        hops = max(1, min(int(hops), 4))  # bound + validate before interpolation
        rows = self._run(
            f"""
            MATCH path = (e:Entity {{key: $key}})-[*1..{hops}]-(:Entity)
            WITH relationships(path) AS rels
            UNWIND rels AS r
            RETURN DISTINCT startNode(r).name AS source, type(r) AS type,
                   endNode(r).name AS target LIMIT 100
            """,
            key=entity_name.strip().lower(),
        )
        if not rows:
            return f"No graph connections found for '{entity_name}'."
        lines = [f"- {r['source']} —[{r['type']}]→ {r['target']}" for r in rows]
        return f"Relations around '{entity_name}':\n" + "\n".join(lines)

    def get_entity(self, name: str) -> dict:
        rows = self._run(
            """
            MATCH (e:Entity {key: $key})
            OPTIONAL MATCH (e)-[r]-(n:Entity)
            RETURN e.name AS name, e.type AS type, e.description AS description,
                   collect(DISTINCT n.name)[0..25] AS connected
            """,
            key=name.strip().lower(),
        )
        if not rows:
            return {}
        row = rows[0]
        return {
            "name": row["name"],
            "type": row["type"],
            "description": row["description"],
            "connected": row["connected"],
        }

    def fulltext_entities(self, query: str, k: int = 5) -> list[str]:
        rows = self._run(
            """
            CALL db.index.fulltext.queryNodes('entity_fulltext', $q, {limit: $k})
            YIELD node WHERE node.corpus = $corpus
            RETURN node.name AS name
            """,
            q=_escape(query),
            k=k,
        )
        return [r["name"] for r in rows]

    def fulltext_chunks(self, query: str, k: int = 8) -> list[RetrievedChunk]:
        rows = self._run(
            """
            CALL db.index.fulltext.queryNodes('chunk_fulltext', $q, {limit: $k})
            YIELD node, score WHERE node.corpus = $corpus
            RETURN node.id AS id, node.text AS text, node.source AS source, score
            """,
            q=_escape(query),
            k=k,
        )
        return [
            RetrievedChunk(
                chunk_id=r["id"], text=r["text"], source=r["source"],
                score=float(r["score"]), retriever="fulltext",
            )
            for r in rows
        ]

    def chunks_for_entities(self, entity_names: list[str], limit: int = 12) -> list[RetrievedChunk]:
        keys = [n.strip().lower() for n in entity_names]
        rows = self._run(
            """
            MATCH (c:Chunk)-[:MENTIONS]->(e:Entity)
            WHERE e.key IN $keys AND c.corpus = $corpus
            WITH c, count(DISTINCT e) AS hits
            RETURN c.id AS id, c.text AS text, c.source AS source, hits
            ORDER BY hits DESC LIMIT $limit
            """,
            keys=keys,
            limit=limit,
        )
        return [
            RetrievedChunk(
                chunk_id=r["id"], text=r["text"], source=r["source"],
                score=float(r["hits"]), retriever="graph",
            )
            for r in rows
        ]


def _escape(query: str) -> str:
    """Escape Lucene special chars so a raw user query can't break the syntax."""
    specials = r'+-&|!(){}[]^"~*?:\/'
    out = []
    for ch in query:
        if ch in specials:
            out.append("\\" + ch)
        else:
            out.append(ch)
    escaped = "".join(out).strip()
    return escaped or "*"
