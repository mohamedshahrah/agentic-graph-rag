import pytest

from llmlens_server.pricing import PricingTable, compute_cost


def test_exact_match():
    t = PricingTable.from_seed()
    # 1k in + 1k out on gpt-4o = 0.0025 + 0.010
    assert compute_cost(t, "openai", "gpt-4o", 1000, 1000) == pytest.approx(0.0125)


def test_prefix_match_dated_snapshot():
    t = PricingTable.from_seed()
    assert compute_cost(t, "openai", "gpt-4o-2024-08-06", 1000, 0) == pytest.approx(0.0025)


def test_unknown_model_returns_none():
    t = PricingTable.from_seed()
    assert compute_cost(t, "acme", "mystery-1", 100, 100) is None


def test_free_provider_default():
    t = PricingTable.from_seed()
    assert compute_cost(t, "ollama", "gemma4:e4b", 1000, 1000) == 0.0
