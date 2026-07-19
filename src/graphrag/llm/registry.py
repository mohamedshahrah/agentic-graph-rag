"""The chat-model registry: which (provider, model) pairs a request may use.

User-facing model selection must never pass raw strings into a provider
client — the request names a model id, the registry decides whether it is
allowed and returns the validated pair. Unknown or disabled ids fall back to
the default instead of erroring, so a stale UI selection degrades gracefully.
"""

from __future__ import annotations

from graphrag.config.settings import AllowedModel, Settings


def allowed_models(settings: Settings) -> list[AllowedModel]:
    """The selectable models. An empty `llm.allowed` means the configured
    default model is the only choice."""
    if settings.llm.allowed:
        return list(settings.llm.allowed)
    return [
        AllowedModel(
            provider=settings.llm.provider,
            model=settings.llm.model,
            label=settings.llm.model,
            default=True,
        )
    ]


def resolve_model(
    requested: str | None,
    settings: Settings,
    enabled: list[str] | None = None,
) -> AllowedModel:
    """Map a request-supplied model id to an allowed (provider, model) pair.

    `enabled` optionally narrows the YAML list further (admin-controlled). An
    empty admin list must not brick chat, so it is ignored rather than honored.
    """
    models = allowed_models(settings)
    if enabled:
        models = [m for m in models if m.model in enabled] or models
    if requested:
        for m in models:
            if m.model == requested:
                return m
    return next((m for m in models if m.default), models[0])
