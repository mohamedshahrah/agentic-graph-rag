"""The llmlens observability hook — the RAG side of the integration.

The feature must be inert unless switched on: disabled setup returns False and
`query_trace` is a real no-op (so the query path pays nothing), while enabled
setup configures the SDK and instruments LangChain.
"""

from __future__ import annotations

import contextlib

from graphrag.config import ObservabilityCfg


class _Settings:
    def __init__(self, cfg: ObservabilityCfg) -> None:
        self.observability = cfg


class _Secrets:
    llmlens_url = None
    llmlens_api_key = None


def test_disabled_setup_is_inert(monkeypatch):
    import graphrag.observability as obs

    monkeypatch.setattr(obs, "_ACTIVE", False, raising=False)
    ok = obs.setup_observability(_Settings(ObservabilityCfg(enabled=False)), _Secrets())
    assert ok is False
    assert obs.is_active() is False
    # A no-op context manager — cheap, and it must not import/drive the SDK.
    with obs.query_trace("agent_query", user_id="u1") as t:
        assert t is None
    assert isinstance(obs.query_trace("x"), contextlib.nullcontext)


def test_enabled_setup_instruments_langchain(monkeypatch):
    import graphrag.observability as obs

    monkeypatch.setattr(obs, "_ACTIVE", False, raising=False)
    ok = obs.setup_observability(
        _Settings(ObservabilityCfg(enabled=True, url="http://127.0.0.1:8100")), _Secrets()
    )
    # langchain-core is a hard dependency of this app, so the handler registers.
    assert ok is True
    assert obs.is_active() is True
    # Now query_trace yields a real trace context (not the nullcontext).
    assert not isinstance(obs.query_trace("agent_query"), contextlib.nullcontext)
    monkeypatch.setattr(obs, "_ACTIVE", False, raising=False)  # leave global clean
