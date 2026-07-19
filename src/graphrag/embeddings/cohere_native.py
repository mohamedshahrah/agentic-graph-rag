"""Cohere embeddings via the native SDK.

The LangChain wrapper (langchain-cohere 0.6) predates embed-v4.0's controls —
`input_type` is fixed and `output_dimension` isn't exposed — so this calls the
SDK directly, same as the Cohere rerank path already does. embed-v4.0 is
Matryoshka-trained: 1024 dims trades a sliver of recall for a third less
vector storage than the 1536 default, the right trade on a small VPS.
"""

from __future__ import annotations

import time

from graphrag.config.settings import EmbeddingCfg
from graphrag.core.errors import ProviderError
from graphrag.core.logging import get_logger
from graphrag.embeddings.base import Embedder

log = get_logger(__name__)

_BATCH = 96  # Cohere's per-request text cap
_DEFAULT_DIM = 1024
_ATTEMPTS = 4


def _retryable(exc: Exception) -> bool:
    name = type(exc).__name__
    return any(s in name for s in ("TooManyRequests", "ServiceUnavailable", "InternalServer"))


class CohereEmbedder(Embedder):
    def __init__(self, cfg: EmbeddingCfg, api_key: str | None) -> None:
        try:
            import cohere
        except ImportError as exc:  # pragma: no cover
            raise ProviderError(
                "Cohere embeddings need the SDK. Install with: pip install '.[extras]'"
            ) from exc
        if not api_key:
            raise ProviderError("COHERE_API_KEY is not set")
        self._client = cohere.ClientV2(api_key=api_key)
        self._model = cfg.model
        self.dim = cfg.dimensions or _DEFAULT_DIM

    def _call(self, batch: list[str], input_type: str) -> list[list[float]]:
        delay = 2.0
        for attempt in range(_ATTEMPTS):
            try:
                res = self._client.embed(
                    model=self._model,
                    texts=batch,
                    input_type=input_type,
                    output_dimension=self.dim,
                    embedding_types=["float"],
                )
                return [list(v) for v in res.embeddings.float_]
            except Exception as exc:
                if attempt == _ATTEMPTS - 1 or not _retryable(exc):
                    raise
                log.warning("cohere_embed_retry", attempt=attempt + 1, error=str(exc))
                time.sleep(delay)
                delay *= 2
        raise ProviderError("unreachable")  # pragma: no cover

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), _BATCH):
            out.extend(self._call(texts[i : i + _BATCH], input_type))
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "search_document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "search_query")[0]
