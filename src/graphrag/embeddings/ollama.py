"""Embeddings from a local Ollama server.

Ollama runs the model itself, so it owns pooling, sequence length, and device —
those `EmbeddingCfg` knobs cannot reach it and are warned about at startup. The
rest (prefixes, normalization, Matryoshka truncation) are plain text/vector math
and are applied here, so they behave exactly as they do for sentence-transformers.
"""

from __future__ import annotations

import numpy as np

from graphrag.config.settings import EmbeddingCfg
from graphrag.core.errors import ProviderError
from graphrag.core.logging import get_logger
from graphrag.embeddings.base import Embedder

log = get_logger(__name__)

# Decided by the Ollama server; we can't influence them over the embed API.
_SERVER_OWNED = ("pooling", "max_seq_length", "device")


class OllamaEmbedder(Embedder):
    def __init__(self, cfg: EmbeddingCfg, base_url: str) -> None:
        try:
            from langchain_ollama import OllamaEmbeddings
        except ImportError as exc:  # pragma: no cover
            raise ProviderError("langchain-ollama is not installed") from exc

        self.cfg = cfg
        self._backend = OllamaEmbeddings(model=cfg.model, base_url=base_url)

        defaults = EmbeddingCfg()
        ignored = [k for k in _SERVER_OWNED if getattr(cfg, k) != getattr(defaults, k)]
        if ignored:
            log.warning("ollama_embed_settings_ignored", settings=ignored, model=cfg.model)

        # Ollama doesn't report the dimension, and guessing it would silently
        # build a mis-sized vector index. Probe once — this also fails fast if
        # the server is unreachable or the model was never pulled.
        try:
            probe = self._backend.embed_query("dimension probe")
        except Exception as exc:
            raise ProviderError(
                f"Ollama at {base_url} could not embed with '{cfg.model}' — "
                f"is the server up and the model pulled (ollama pull {cfg.model})?"
            ) from exc
        self.dim = cfg.dimensions or len(probe)

    def _finish(self, vectors: list[list[float]]) -> list[list[float]]:
        arr = np.asarray(vectors, dtype=np.float32)
        if self.cfg.dimensions:
            arr = arr[:, : self.cfg.dimensions]
        if self.cfg.normalize:
            arr = arr / np.clip(np.linalg.norm(arr, axis=1, keepdims=True), 1e-12, None)
        return arr.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        prefixed = [self.cfg.document_prefix + t for t in texts]
        return self._finish(self._backend.embed_documents(prefixed))

    def embed_query(self, text: str) -> list[float]:
        return self._finish([self._backend.embed_query(self.cfg.query_prefix + text)])[0]
