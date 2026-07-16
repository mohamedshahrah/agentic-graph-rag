"""Loader registry + a `load_path` dispatcher over a directory or single file."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from graphrag.core.errors import IngestionError
from graphrag.core.types import Document
from graphrag.ingestion.loaders.base import Loader
from graphrag.ingestion.loaders.image import ImageLoader
from graphrag.ingestion.loaders.pdf import PDFLoader
from graphrag.ingestion.loaders.text import TextLoader
from graphrag.ocr.base import OCREngine


def build_loaders(ocr: OCREngine | None = None, min_text_chars: int = 100) -> list[Loader]:
    return [
        TextLoader(),
        PDFLoader(ocr=ocr, min_text_chars=min_text_chars),
        ImageLoader(ocr=ocr),
    ]


def _pick(loaders: list[Loader], path: Path) -> Loader | None:
    return next((ld for ld in loaders if ld.supports(path)), None)


def iter_documents(
    path: str | Path, ocr: OCREngine | None = None, min_text_chars: int = 100
) -> Iterator[Document]:
    """Yield a Document for every supported file under `path` (file or folder)."""
    root = Path(path)
    loaders = build_loaders(ocr, min_text_chars=min_text_chars)
    files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
    matched = False
    for file in files:
        loader = _pick(loaders, file)
        if loader is None:
            continue
        matched = True
        yield loader.load(file)
    if not matched:
        raise IngestionError(f"No supported files found at: {path}")


__all__ = ["Loader", "build_loaders", "iter_documents"]
