"""Local embeddings via sentence-transformers. This is where the fine-grained
control lives: device, pooling, normalization, prefixes, and Matryoshka
dimension truncation."""

from __future__ import annotations

from graphrag.config.settings import EmbeddingCfg
from graphrag.core.errors import ProviderError
from graphrag.embeddings.base import Embedder


def _resolve_device(device: str) -> str | None:
    if device != "auto":
        return device
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


class SentenceTransformerEmbedder(Embedder):
    def __init__(self, cfg: EmbeddingCfg) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise ProviderError(
                "embeddings.provider 'sentence_transformers' runs the model in-process "
                "and needs an optional extra: pip install '.[local-models]'. "
                "To embed without it, use provider 'ollama' (or an API provider)."
            ) from exc

        self.cfg = cfg
        self._model = SentenceTransformer(cfg.model, device=_resolve_device(cfg.device))
        self._model.max_seq_length = cfg.max_seq_length
        # Report the (possibly truncated) output dimension.
        full = self._model.get_sentence_embedding_dimension()
        self.dim = cfg.dimensions or full

    def _encode(self, texts: list[str]) -> list[list[float]]:
        kwargs: dict = {
            "batch_size": self.cfg.batch_size,
            "normalize_embeddings": self.cfg.normalize,
            "convert_to_numpy": True,
        }
        if self.cfg.dimensions:
            # Matryoshka truncation (supported by bge-m3, nomic, etc.).
            kwargs["truncate_dim"] = self.cfg.dimensions
        vectors = self._model.encode(texts, **kwargs)
        return vectors.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        prefixed = [self.cfg.document_prefix + t for t in texts]
        return self._encode(prefixed)

    def embed_query(self, text: str) -> list[float]:
        return self._encode([self.cfg.query_prefix + text])[0]
