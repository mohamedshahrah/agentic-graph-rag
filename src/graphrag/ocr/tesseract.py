"""Offline OCR fallback via Tesseract. No API keys, no model download."""

from __future__ import annotations

import io

from graphrag.config.settings import OCRCfg
from graphrag.core.errors import ProviderError
from graphrag.ocr.base import OCREngine


class TesseractOCR(OCREngine):
    def __init__(self, cfg: OCRCfg) -> None:
        self._lang = cfg.tesseract.lang

    def extract_text(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        try:
            import pytesseract
            from PIL import Image
        except ImportError as exc:  # pragma: no cover
            raise ProviderError("pytesseract / Pillow not installed") from exc
        image = Image.open(io.BytesIO(image_bytes))
        return pytesseract.image_to_string(image, lang=self._lang)
