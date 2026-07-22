"""Seed model prices (USD per 1K tokens). Approximate + configurable — the point
is the mechanism, not perfectly current numbers. Update via the model_pricing
table or by editing this list."""

# (provider, model, input_per_1k, output_per_1k)
SEED_PRICING: list[tuple[str, str, float, float]] = [
    # Anthropic
    ("anthropic", "claude-opus-4-8", 0.005, 0.025),
    ("anthropic", "claude-sonnet-5", 0.003, 0.015),
    ("anthropic", "claude-haiku-4-5", 0.001, 0.005),
    ("anthropic", "claude-fable-5", 0.010, 0.050),
    ("anthropic", "claude-3-5-sonnet", 0.003, 0.015),
    # OpenAI
    ("openai", "gpt-4o", 0.0025, 0.010),
    ("openai", "gpt-4o-mini", 0.00015, 0.0006),
    ("openai", "gpt-4.1", 0.002, 0.008),
    ("openai", "gpt-4-turbo", 0.010, 0.030),
    ("openai", "o3-mini", 0.0011, 0.0044),
    # Google
    ("google", "gemini-2.5-flash", 0.0003, 0.0025),
    ("google", "gemini-2.5-pro", 0.00125, 0.010),
    ("google", "gemini-1.5-flash", 0.000075, 0.0003),
    # Local / open (free)
    ("ollama", "", 0.0, 0.0),
]
