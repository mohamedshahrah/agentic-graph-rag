"""Build a LangChain chat model for any provider from one config shape.

Every returned model exposes the same interface (`.invoke`, `.astream`,
`.bind_tools`), which is what lets the agent be provider-agnostic and lets you
swap local <-> API with a single config line.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from graphrag.config.settings import Secrets
from graphrag.core.errors import ProviderError


def build_chat_model(
    provider: str,
    model: str,
    secrets: Secrets,
    *,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    extra: dict[str, Any] | None = None,
) -> BaseChatModel:
    extra = extra or {}
    try:
        if provider == "ollama":
            from langchain_ollama import ChatOllama

            return ChatOllama(
                model=model,
                base_url=secrets.ollama_base_url,
                temperature=temperature,
                num_predict=max_tokens,
                **extra,
            )
        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model=model,
                api_key=secrets.anthropic_api_key,
                temperature=temperature,
                max_tokens=max_tokens,
                **extra,
            )
        if provider == "openai":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=model,
                api_key=secrets.openai_api_key,
                temperature=temperature,
                max_tokens=max_tokens,
                **extra,
            )
        if provider == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model=model,
                google_api_key=secrets.google_api_key,
                temperature=temperature,
                max_output_tokens=max_tokens,
                **extra,
            )
    except ImportError as exc:  # pragma: no cover
        raise ProviderError(f"LLM provider '{provider}' package is not installed") from exc

    raise ProviderError(f"Unknown LLM provider: {provider}")
