"""Image loader: runs OCR to turn a picture into embeddable text."""

from __future__ import annotations

from pathlib import Path

from graphrag.core.errors import IngestionError
from graphrag.core.types import Document
from graphrag.ingestion.loaders.base import Loader
from graphrag.ocr.base import OCREngine

_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
}


class ImageLoader(Loader):
    suffixes = tuple(_MIME.keys())

    def __init__(self, ocr: OCREngine | None = None) -> None:
        self._ocr = ocr

    def load(self, path: Path) -> Document:
        if self._ocr is None:
            raise IngestionError("OCR is disabled; cannot ingest image files")
        mime = _MIME.get(path.suffix.lower(), "image/png")
        text = self._ocr.extract_text(path.read_bytes(), mime)
        return Document(source=str(path), content=text, metadata={"type": "image", "ocr": True})
