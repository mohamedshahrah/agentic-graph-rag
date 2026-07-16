"""API-based embedders (OpenAI, Gemini, Voyage, Cohere), wrapped behind our
`Embedder` interface via their LangChain integrations."""

from __future__ import annotations

from graphrag.config.settings import EmbeddingCfg, Secrets
from graphrag.core.errors import ProviderError
from graphrag.embeddings.base import Embedder

# Sensible defaults so we can report `dim` without a network round-trip.
_KNOWN_DIMS = {
    "text-embedding-3-large": 3072,
    "text-embedding-3-small": 1536,
    "voyage-3-large": 1024,
    "voyage-3": 1024,
    "embed-v4.0": 1536,
    "models/text-embedding-004": 768,
}


class LangChainEmbedder(Embedder):
    """Adapts any LangChain `Embeddings` object to our interface."""

    def __init__(self, backend, cfg: EmbeddingCfg) -> None:
        self._backend = backend
        self.dim = cfg.dimensions or _KNOWN_DIMS.get(cfg.model, 1024)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._backend.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._backend.embed_query(text)


def build_api_embedder(cfg: EmbeddingCfg, secrets: Secrets) -> Embedder:
    provider = cfg.provider
    try:
        if provider == "openai":
            from langchain_openai import OpenAIEmbeddings

            backend = OpenAIEmbeddings(
                model=cfg.model,
                api_key=secrets.openai_api_key,
                dimensions=cfg.dimensions,
            )
        elif provider == "gemini":
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            backend = GoogleGenerativeAIEmbeddings(
                model=cfg.model, google_api_key=secrets.google_api_key
            )
        elif provider == "voyage":
            from langchain_voyageai import VoyageAIEmbeddings

            backend = VoyageAIEmbeddings(model=cfg.model, api_key=secrets.voyage_api_key)
        elif provider == "cohere":
            from langchain_cohere import CohereEmbeddings

            backend = CohereEmbeddings(model=cfg.model, cohere_api_key=secrets.cohere_api_key)
        else:
            raise ProviderError(f"Unknown embedding provider: {provider}")
    except ImportError as exc:  # pragma: no cover
        raise ProviderError(
            f"Provider '{provider}' needs an extra package. Install with: pip install '.[extras]'"
        ) from exc

    return LangChainEmbedder(backend, cfg)
