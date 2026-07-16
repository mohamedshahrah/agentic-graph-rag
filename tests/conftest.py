"""Shared test fixtures."""

from __future__ import annotations

import pytest

from graphrag.core.types import RetrievedChunk


@pytest.fixture
def make_chunk():
    def _make(chunk_id: str, text: str = "x", score: float = 1.0) -> RetrievedChunk:
        return RetrievedChunk(chunk_id=chunk_id, text=text, source="s", score=score)

    return _make
