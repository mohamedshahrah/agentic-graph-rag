"""Small, explicit error taxonomy. Catch these instead of bare Exception."""


class GraphRAGError(Exception):
    """Base class for every error this project raises deliberately."""


class ConfigError(GraphRAGError):
    """Invalid or missing configuration."""


class ProviderError(GraphRAGError):
    """A model provider (LLM / embeddings / OCR / rerank) failed or is misconfigured."""


class StorageError(GraphRAGError):
    """A storage backend (graph or vector) failed or is unreachable."""


class IngestionError(GraphRAGError):
    """A document could not be loaded, chunked, or extracted."""
