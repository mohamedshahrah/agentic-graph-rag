"""Chunker factory. `chunking.strategy` picks recursive | token | semantic."""

from __future__ import annotations

from graphrag.config.settings import ChunkingCfg, EmbeddingCfg
from graphrag.core.errors import ConfigError
from graphrag.embeddings.base import Embedder
from graphrag.ingestion.chunking.base import Chunker
from graphrag.ingestion.chunking.recursive import RecursiveChunker
from graphrag.ingestion.chunking.semantic import SemanticChunker
from graphrag.ingestion.chunking.token import TokenChunker
from graphrag.ingestion.chunking.tokenizer import TokenCounter, load_hf_tokenizer


def build_chunker(
    cfg: ChunkingCfg, embed_cfg: EmbeddingCfg, embedder: Embedder | None = None
) -> Chunker:
    tokenizer = load_hf_tokenizer(embed_cfg.tokenizer or embed_cfg.model)
    counter = TokenCounter(tokenizer)

    if cfg.strategy == "token":
        return TokenChunker(tokenizer, cfg.max_tokens, cfg.overlap)
    if cfg.strategy == "recursive":
        return RecursiveChunker(counter, cfg.max_tokens, cfg.overlap, tokenizer)
    if cfg.strategy == "semantic":
        if embedder is None:
            raise ConfigError("Semantic chunking needs an embedder")
        return SemanticChunker(
            embedder,
            counter,
            cfg.semantic.threshold,
            cfg.max_tokens,
            cfg.semantic.min_chunk_tokens,
        )
    raise ConfigError(f"Unknown chunking strategy: {cfg.strategy}")


__all__ = ["Chunker", "build_chunker"]
