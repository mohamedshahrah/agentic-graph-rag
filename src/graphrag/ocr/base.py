"""OCR interface: image bytes -> extracted text."""

from __future__ import annotations

import abc


class OCREngine(abc.ABC):
    @abc.abstractmethod
    def extract_text(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        ...
