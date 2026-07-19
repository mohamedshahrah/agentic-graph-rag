"""Cohere embed-v4.0 wiring. The SDK is stubbed — these check the parameters we
send, which is what the LangChain wrapper couldn't express."""

import sys
import types

import pytest

from graphrag.config.settings import EmbeddingCfg
from graphrag.core.errors import ProviderError


class _FakeEmbeddings:
    def __init__(self, vectors):
        self.float_ = vectors


class _FakeClient:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.calls: list[dict] = []

    def embed(self, **kwargs):
        self.calls.append(kwargs)
        return types.SimpleNamespace(
            embeddings=_FakeEmbeddings([[0.1] * 1024 for _ in kwargs["texts"]])
        )


@pytest.fixture
def cohere_stub(monkeypatch):
    created: list[_FakeClient] = []

    def _client(api_key=None):
        c = _FakeClient(api_key)
        created.append(c)
        return c

    module = types.ModuleType("cohere")
    module.ClientV2 = _client
    monkeypatch.setitem(sys.modules, "cohere", module)
    return created


def _embedder(cohere_stub, **kw):
    from graphrag.embeddings.cohere_native import CohereEmbedder

    cfg = EmbeddingCfg(provider="cohere", model="embed-v4.0", **kw)
    return CohereEmbedder(cfg, "key-123"), cohere_stub


def test_documents_and_queries_use_different_input_types(cohere_stub):
    """Asymmetric embedding is the whole point of input_type — getting this
    wrong degrades retrieval silently."""
    emb, clients = _embedder(cohere_stub, dimensions=1024)
    emb.embed_documents(["a", "b"])
    emb.embed_query("q")
    assert clients[0].calls[0]["input_type"] == "search_document"
    assert clients[0].calls[1]["input_type"] == "search_query"


def test_output_dimension_is_requested_and_reported(cohere_stub):
    emb, clients = _embedder(cohere_stub, dimensions=512)
    emb.embed_documents(["a"])
    assert clients[0].calls[0]["output_dimension"] == 512
    assert emb.dim == 512


def test_defaults_to_1024_dims(cohere_stub):
    emb, _ = _embedder(cohere_stub)
    assert emb.dim == 1024


def test_large_batches_are_split_to_the_api_limit(cohere_stub):
    emb, clients = _embedder(cohere_stub)
    out = emb.embed_documents([f"t{i}" for i in range(200)])
    assert len(out) == 200
    assert [len(c["texts"]) for c in clients[0].calls] == [96, 96, 8]


def test_embed_query_returns_a_single_vector(cohere_stub):
    emb, _ = _embedder(cohere_stub)
    assert len(emb.embed_query("q")) == 1024


def test_missing_api_key_fails_loudly(cohere_stub):
    from graphrag.embeddings.cohere_native import CohereEmbedder

    with pytest.raises(ProviderError, match="COHERE_API_KEY"):
        CohereEmbedder(EmbeddingCfg(provider="cohere", model="embed-v4.0"), None)
