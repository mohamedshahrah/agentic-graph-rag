"""Tokenizer helper. The chunkers use the *embedding model's own* tokenizer so
chunk sizes are measured in the exact tokens the embedder will see."""

from __future__ import annotations

from graphrag.core.logging import get_logger

log = get_logger(__name__)


def load_hf_tokenizer(model_name: str):
    """Return a HuggingFace tokenizer for `model_name`, or None if unavailable
    (e.g. an API embedder with no local tokenizer)."""
    try:
        from transformers import AutoTokenizer

        return AutoTokenizer.from_pretrained(model_name)
    except Exception as exc:  # network / gated / API-only model
        log.warning("tokenizer_unavailable", model=model_name, error=str(exc))
        return None


class TokenCounter:
    """Counts tokens with an HF tokenizer when available, else a fast heuristic
    (~1.3 tokens per whitespace word) so recursive/semantic chunking still work
    with API embedders."""

    def __init__(self, tokenizer=None) -> None:
        self._tok = tokenizer

    def count(self, text: str) -> int:
        if self._tok is not None:
            return len(self._tok.encode(text, add_special_tokens=False))
        return max(1, int(len(text.split()) * 1.3))
