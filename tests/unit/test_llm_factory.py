"""Provider wiring in the chat-model factory."""

import pytest

from graphrag.config.settings import Secrets
from graphrag.core.errors import ProviderError
from graphrag.llm import build_chat_model


@pytest.fixture
def secrets() -> Secrets:
    return Secrets(
        DEEPSEEK_API_KEY="ds-test", DASHSCOPE_API_KEY="qw-test", OPENAI_API_KEY="oa-test"
    )


def test_deepseek_uses_its_own_endpoint_and_key(secrets):
    """DeepSeek is OpenAI-compatible, so the risk is silently talking to
    OpenAI with a DeepSeek key (or vice versa)."""
    m = build_chat_model("deepseek", "deepseek-v4-flash", secrets)
    assert "api.deepseek.com" in str(m.openai_api_base)
    assert m.openai_api_key.get_secret_value() == "ds-test"


def test_qwen_uses_dashscope_compatible_mode(secrets):
    m = build_chat_model("qwen", "qwen3.6-plus", secrets)
    assert "dashscope" in str(m.openai_api_base)
    assert "compatible-mode" in str(m.openai_api_base)
    assert m.openai_api_key.get_secret_value() == "qw-test"


def test_openai_keeps_its_default_endpoint(secrets):
    m = build_chat_model("openai", "gpt-4o-mini", secrets)
    assert "deepseek" not in str(m.openai_api_base or "")
    assert "dashscope" not in str(m.openai_api_base or "")


def test_unknown_provider_is_rejected(secrets):
    with pytest.raises(ProviderError, match="Unknown LLM provider"):
        build_chat_model("nope", "x", secrets)
