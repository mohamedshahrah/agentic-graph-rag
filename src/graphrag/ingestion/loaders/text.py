"""Plain text / Markdown loader."""

from __future__ import annotations

from pathlib import Path

from graphrag.core.types import Document
from graphrag.ingestion.loaders.base import Loader


class TextLoader(Loader):
    suffixes = (".txt", ".md", ".markdown", ".rst")

    def load(self, path: Path) -> Document:
        content = path.read_text(encoding="utf-8", errors="ignore")
        return Document(source=str(path), content=content, metadata={"type": "text"})
