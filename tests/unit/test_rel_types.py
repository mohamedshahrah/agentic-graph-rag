"""Relation types are interpolated into the graph as relationship *types* —
whatever the LLM emits must come out as bounded UPPER_SNAKE or the fallback."""

import pytest

from graphrag.ingestion.extraction.graph_extractor import _rel_type


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("FOUNDED", "FOUNDED"),
        ("works for", "WORKS_FOR"),
        ("Part-Of", "PART_OF"),
        ("uses`) DETACH DELETE (n", "USES_DETACH_DELETE_N"),
        ("", "RELATED_TO"),
        ("123", "RELATED_TO"),  # must start with a letter
        ("a" * 100, "A" * 40),  # bounded
    ],
)
def test_rel_type_normalization(raw, expected):
    assert _rel_type(raw) == expected
