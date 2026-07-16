"""Generative reranking — score parsing and ordering.

Ollama has no cross-encoder endpoint, so a local reranker leans on a chat model
returning a bare number. These cover what happens when it doesn't.
"""

from types import SimpleNamespace

import pytest

from graphrag.config.settings import RerankCfg, Secrets
from graphrag.retrieval import reranker as rr


class _FakeLLM:
    """Replies are keyed by document text, not call order — `rerank` scores
    candidates concurrently, so order isn't deterministic."""

    def __init__(self, by_doc: dict[str, str]) -> None:
        self.by_doc = by_doc

    def invoke(self, prompt: str):
        for doc, reply in self.by_doc.items():
            if doc in prompt:
                return SimpleNamespace(content=reply)
        raise AssertionError(f"unexpected document in prompt: {prompt!r}")


@pytest.fixture
def build(monkeypatch):
    def _build(by_doc: dict[str, str], **cfg_kwargs):
        monkeypatch.setattr(rr, "build_chat_model", lambda *a, **k: _FakeLLM(by_doc))
        cfg = RerankCfg(provider="ollama", model="fake-model", **cfg_kwargs)
        return rr.build_reranker(cfg, Secrets())

    return _build


def test_dispatches_to_generative_reranker(build):
    assert isinstance(build({}), rr.LLMReranker)


def test_orders_by_model_score(build, make_chunk):
    reranker = build({"good": "9", "meh": "4", "bad": "1"}, concurrency=2)
    chunks = [make_chunk("c1", "bad"), make_chunk("c2", "good"), make_chunk("c3", "meh")]
    out = reranker.rerank("q", chunks, top_k=3)
    assert [c.chunk_id for c in out] == ["c2", "c3", "c1"]
    assert out[0].score == pytest.approx(0.9)  # 0-10 reply normalized to 0-1


def test_unscorable_chunks_keep_retrieval_order_instead_of_being_dropped(build, make_chunk):
    # A model that ignores "reply with only the number" must not cost us recall.
    reranker = build({"good": "8", "chatty": "I'm unable to rate that."})
    chunks = [make_chunk("c1", "chatty", score=0.5), make_chunk("c2", "good")]
    out = reranker.rerank("q", chunks, top_k=5)
    assert [c.chunk_id for c in out] == ["c2", "c1"]
    assert out[1].score == 0.5  # fell back to its retrieval score


def test_out_of_range_score_is_clamped(build, make_chunk):
    reranker = build({"x": "99"})
    out = reranker.rerank("q", [make_chunk("c1", "x")], top_k=1)
    assert out[0].score == 1.0


def test_respects_top_k(build, make_chunk):
    reranker = build({"a": "9", "b": "8", "c": "7"})
    chunks = [make_chunk("c1", "a"), make_chunk("c2", "b"), make_chunk("c3", "c")]
    out = reranker.rerank("q", chunks, top_k=2)
    assert [c.chunk_id for c in out] == ["c1", "c2"]


def test_empty_candidates(build):
    assert build({}).rerank("q", [], top_k=5) == []


def test_ollama_defaults_to_reasoning_off(monkeypatch):
    # Thinking burns the token budget and returns empty content -> no score.
    captured = {}

    def _capture(provider, model, secrets, **kwargs):
        captured.update(kwargs)
        return _FakeLLM({})

    monkeypatch.setattr(rr, "build_chat_model", _capture)
    rr.build_reranker(RerankCfg(provider="ollama", model="m"), Secrets())
    assert captured["extra"]["reasoning"] is False


def test_explicit_reasoning_is_not_overridden(monkeypatch):
    captured = {}

    def _capture(provider, model, secrets, **kwargs):
        captured.update(kwargs)
        return _FakeLLM({})

    monkeypatch.setattr(rr, "build_chat_model", _capture)
    rr.build_reranker(
        RerankCfg(provider="ollama", model="m", extra={"reasoning": True}), Secrets()
    )
    assert captured["extra"]["reasoning"] is True
