"""Request-supplied model ids are validated against an allowlist, never passed
through raw."""

import pytest

from graphrag.config.settings import AllowedModel, LLMCfg, Settings
from graphrag.llm.registry import allowed_models, resolve_model


def _settings(*allowed: AllowedModel) -> Settings:
    return Settings(
        llm=LLMCfg(provider="gemini", model="gemini-3.5-flash", allowed=list(allowed))
    )


GEMINI = AllowedModel(provider="gemini", model="gemini-3.5-flash", default=True)
QWEN = AllowedModel(provider="qwen", model="qwen3.6-plus")


def test_empty_allowlist_offers_only_the_configured_model():
    models = allowed_models(_settings())
    assert [(m.provider, m.model) for m in models] == [("gemini", "gemini-3.5-flash")]
    assert models[0].default


def test_allowed_model_resolves_to_its_own_provider():
    m = resolve_model("qwen3.6-plus", _settings(GEMINI, QWEN))
    assert (m.provider, m.model) == ("qwen", "qwen3.6-plus")


@pytest.mark.parametrize("requested", [None, "", "gpt-9-ultra", "../../etc/passwd"])
def test_unknown_or_missing_model_falls_back_to_default(requested):
    assert resolve_model(requested, _settings(GEMINI, QWEN)).model == "gemini-3.5-flash"


def test_first_entry_is_used_when_none_is_marked_default():
    s = _settings(QWEN, AllowedModel(provider="gemini", model="gemini-3.1-flash-lite"))
    assert resolve_model(None, s).model == "qwen3.6-plus"


def test_admin_enabled_list_narrows_the_choices():
    assert resolve_model("qwen3.6-plus", _settings(GEMINI, QWEN), enabled=["gemini-3.5-flash"]) \
        .model == "gemini-3.5-flash"


def test_empty_admin_list_does_not_brick_chat():
    """An admin disabling every model must not make chat unusable."""
    assert resolve_model("qwen3.6-plus", _settings(GEMINI, QWEN), enabled=[]).model
