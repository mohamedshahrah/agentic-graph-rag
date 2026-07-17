"""The composition root.

`Container` holds the heavy, shared singletons — the embedding model, the
reranker model, the LLM client, the Neo4j driver, Redis. These are built once and
reused by every user.

`Tenant` is a lightweight, per-user view: it binds cheap store/retriever/agent
wrappers to that user's isolated namespace while reusing the container's shared
models. This is the memory optimization — N users cost N sets of small wrappers,
not N copies of the models.
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from functools import cached_property

from graphrag.agent import AgentRunner, build_checkpointer
from graphrag.cache import get_redis
from graphrag.config import Secrets, Settings, load_settings
from graphrag.core.logging import configure_logging, get_logger
from graphrag.embeddings.base import Embedder
from graphrag.ingestion.chunking import build_chunker
from graphrag.ingestion.extraction import LLMGraphExtractor
from graphrag.llm import build_chat_model
from graphrag.ocr import build_ocr
from graphrag.retrieval import (
    GraphAugmentedRetriever,
    HybridRetriever,
    VectorRetriever,
    build_reranker,
)
from graphrag.storage import build_graph_store, build_vector_store
from graphrag.storage.neo4j_client import driver_from_secrets, safe_ident

log = get_logger(__name__)

_USER_RE = re.compile(r"[^a-z0-9_-]+")

# When Redis is down, don't re-attempt a connection on every access — but do
# recover without a restart once it's back.
_REDIS_RETRY_SECONDS = 30.0


def sanitize_user(user_id: str) -> str:
    """Normalize a user id into a safe namespace/database token."""
    clean = _USER_RE.sub("-", (user_id or "").strip().lower()).strip("-")
    return (clean or "default")[:48]


class Tenant:
    """One user's isolated view, built from the container's shared resources."""

    def __init__(self, container: Container, database: str, corpus: str, user_id: str) -> None:
        c = container
        s = c.settings
        self.user_id = user_id
        self.corpus = corpus
        self.database = database

        self.graph_store = build_graph_store(c.driver, database, corpus, s)
        self.vector_store = build_vector_store(c.driver, database, corpus, s)
        self.vector_retriever = VectorRetriever(c.embedder, self.vector_store)
        graph_aug = GraphAugmentedRetriever(self.graph_store, s.retrieval.graph_hops)
        self.hybrid_retriever = HybridRetriever(
            self.vector_retriever, graph_aug, self.graph_store, c.reranker,
            candidate_k=s.retrieval.candidate_k,
        )
        self.agent = AgentRunner(
            c.llm, self.vector_retriever, self.hybrid_retriever, self.graph_store,
            c.embedder,
            checkpointer=c.checkpointer,
            top_k=s.retrieval.top_k, graph_hops=s.retrieval.graph_hops,
            default_style=s.agent.default_style,
            max_tool_iterations=s.agent.max_tool_iterations,
        )
        self._embed_dim = c.embedder.dim

    def setup(self) -> None:
        self.graph_store.setup()
        self.vector_store.setup(self._embed_dim)


class Container:
    def __init__(self, settings: Settings | None = None, secrets: Secrets | None = None) -> None:
        if settings is None or secrets is None:
            settings, secrets = load_settings()
        self.settings = settings
        self.secrets = secrets
        configure_logging(settings.app.log_level)
        self._tenants: OrderedDict[str, Tenant] = OrderedDict()
        self._ready_dbs: set[str] = set()
        self._redis_client = None
        self._redis_checked_at = 0.0
        # The API flips this to True before serving so the checkpointer is built
        # async (its streaming needs the async saver). CLI/scripts stay sync.
        self.async_memory = False

    # -- shared infrastructure ------------------------------------------------
    @property
    def redis(self):
        """Shared Redis client, or None while unreachable. Reconnects lazily
        (at most every _REDIS_RETRY_SECONDS) so a blip at startup doesn't
        disable caching and quotas until the next restart."""
        if self._redis_client is not None:
            return self._redis_client
        now = time.monotonic()
        if now - self._redis_checked_at < _REDIS_RETRY_SECONDS:
            return None
        self._redis_checked_at = now
        try:
            client = get_redis(self.secrets.redis_url)
            client.ping()
            self._redis_client = client
            return client
        except Exception:
            return None

    @cached_property
    def driver(self):
        return driver_from_secrets(self.secrets)

    @cached_property
    def checkpointer(self):
        return build_checkpointer(
            self.secrets.redis_url,
            self.settings.agent.memory,
            use_async=self.async_memory,
            redis_available=self.redis is not None,
        )

    # -- shared models (loaded once, reused by all tenants) -------------------
    @cached_property
    def embedder(self) -> Embedder:
        cfg = self.settings.embeddings
        if cfg.provider == "sentence_transformers":
            from graphrag.embeddings.sentence_transformers import SentenceTransformerEmbedder

            base: Embedder = SentenceTransformerEmbedder(cfg)
        elif cfg.provider == "ollama":
            from graphrag.embeddings.ollama import OllamaEmbedder

            base = OllamaEmbedder(cfg, self.secrets.ollama_base_url)
        else:
            from graphrag.embeddings.api_providers import build_api_embedder

            base = build_api_embedder(cfg, self.secrets)
        if cfg.cache.enabled and self.redis is not None:
            from graphrag.embeddings.cache import CachedEmbedder

            return CachedEmbedder(base, self.redis, cfg.model, cfg.cache.ttl_seconds)
        return base

    @cached_property
    def llm(self):
        c = self.settings.llm
        return build_chat_model(
            c.provider, c.model, self.secrets,
            temperature=c.temperature, max_tokens=c.max_tokens, extra=c.extra,
        )

    @cached_property
    def extractor_llm(self):
        """The chat model extraction (and community summarization) runs on —
        the dedicated `ingestion.llm` when configured, else the main `llm`."""
        cfg = self.settings.ingestion.llm
        if cfg is None:
            return self.llm
        return build_chat_model(
            cfg.provider, cfg.model, self.secrets,
            temperature=cfg.temperature, max_tokens=cfg.max_tokens, extra=cfg.extra,
        )

    @cached_property
    def ocr(self):
        if not self.settings.ocr.enabled:
            return None
        return build_ocr(self.settings.ocr, self.secrets)

    @cached_property
    def chunker(self):
        return build_chunker(self.settings.chunking, self.settings.embeddings, self.embedder)

    @cached_property
    def extractor(self) -> LLMGraphExtractor:
        return LLMGraphExtractor(self.extractor_llm)

    @cached_property
    def reranker(self):
        return build_reranker(self.settings.retrieval.rerank, self.secrets)

    # -- per-user tenants -----------------------------------------------------
    def _resolve_scope(self, user: str) -> tuple[str, str]:
        """Return (database, corpus) for a sanitized user id."""
        t = self.settings.tenancy
        if t.per_tenant_database:
            return safe_ident(t.database_prefix + user.replace("-", "_")), user
        return self.settings.storage.graph.database, user

    def _ensure_database(self, database: str) -> None:
        if not self.settings.tenancy.per_tenant_database:
            return
        try:  # Enterprise-only; degrades gracefully on Community.
            with self.driver.session(database="system") as session:
                session.run(f"CREATE DATABASE {database} IF NOT EXISTS").consume()
        except Exception as exc:
            log.warning("per_tenant_database_unavailable", database=database, error=str(exc))

    def tenant(self, user_id: str | None = None) -> Tenant:
        if not self.settings.tenancy.enabled:
            user_id = None  # single-tenant mode: everyone shares default_user
        user = sanitize_user(user_id or self.settings.tenancy.default_user)
        if user in self._tenants:
            self._tenants.move_to_end(user)
            return self._tenants[user]

        database, corpus = self._resolve_scope(user)
        tenant = Tenant(self, database, corpus, user)

        # Create indexes once per database (constraints/indexes are DB-wide).
        if database not in self._ready_dbs:
            self._ensure_database(database)
            try:
                tenant.setup()
                self._ready_dbs.add(database)
            except Exception as exc:  # don't fail the request if Neo4j is briefly down
                log.warning("tenant_setup_deferred", user=user, error=str(exc))

        self._tenants[user] = tenant
        self._tenants.move_to_end(user)
        while len(self._tenants) > self.settings.tenancy.max_active_tenants:
            self._tenants.popitem(last=False)  # evict LRU (cheap wrappers only)
        return tenant

    # -- lifecycle ------------------------------------------------------------
    def setup_storage(self) -> None:
        """Prepare the default user's namespace. Safe to call repeatedly."""
        self.tenant(self.settings.tenancy.default_user)
