"""PDF loader. Extracts the text layer with pdfplumber and falls back to OCR on
the rendered page image for pages that are really scans.

"Is this a scan?" is a threshold, not a boolean: scanned pages routinely carry a
few characters of text layer (a page number, a scanner header), so testing for an
empty string silently skips OCR on the whole document and ingests a stack of page
labels as if it were the content. See `ocr.min_text_chars`.
"""

from __future__ import annotations

import io
from pathlib import Path

from graphrag.core.logging import get_logger
from graphrag.core.types import Document
from graphrag.ingestion.loaders.base import Loader
from graphrag.ocr.base import OCREngine

log = get_logger(__name__)


class PDFLoader(Loader):
    suffixes = (".pdf",)

    def __init__(self, ocr: OCREngine | None = None, min_text_chars: int = 100) -> None:
        self._ocr = ocr
        self._min_text_chars = min_text_chars

    def load(self, path: Path) -> Document:
        import pdfplumber

        pages: list[str] = []
        ocred = 0
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                if self._ocr is not None and len(text.strip()) < self._min_text_chars:
                    scanned = self._ocr_page(page, i)
                    # Keep whatever read more of the page. OCR returns "" when
                    # rendering fails, and a page label beats nothing.
                    if len(scanned.strip()) > len(text.strip()):
                        text = scanned
                        ocred += 1
                pages.append(text)

        content = "\n\n".join(pages)
        if ocred:
            log.info("pdf_ocr_pages", source=str(path), ocred=ocred, pages=len(pages))
        return Document(
            source=str(path),
            content=content,
            metadata={"type": "pdf", "pages": len(pages), "ocr_pages": ocred},
        )

    def _ocr_page(self, page, index: int) -> str:
        try:
            image = page.to_image(resolution=200).original
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            return self._ocr.extract_text(buf.getvalue(), "image/png")
        except Exception as exc:  # rendering needs poppler; degrade gracefully
            log.warning("pdf_ocr_failed", page=index, error=str(exc))
            return ""
