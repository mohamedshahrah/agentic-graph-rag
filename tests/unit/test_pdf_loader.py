"""Deciding when a PDF page is really a scan.

The trap: scanned pages usually carry a few characters of text layer (a page
number, a scanner header). Testing for an *empty* string skips OCR on those and
ingests the page labels as though they were the document.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from graphrag.ingestion.loaders.pdf import PDFLoader


class _FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _FakeOCR:
    """Stands in for the vision LLM; returns the page's 'real' scanned content."""

    def __init__(self, result: str = "The actual scanned body text of the page.") -> None:
        self.result = result
        self.calls = 0

    def extract_text(self, data: bytes, mime: str) -> str:
        self.calls += 1
        return self.result


def _load(pages, ocr, min_text_chars=100):
    """Drive PDFLoader over fake pages.

    pdfplumber is stubbed via sys.modules rather than patched, so these run
    without the (heavy) real dependency installed. Page rendering is stubbed too
    — what's under test is the decision to OCR, not the rasterizer.
    """
    fake = MagicMock()
    fake.open.return_value.__enter__.return_value.pages = [_FakePage(t) for t in pages]
    loader = PDFLoader(ocr=ocr, min_text_chars=min_text_chars)
    def render(self, page, i):
        return ocr.extract_text(b"", "image/png")

    with (
        patch.dict(sys.modules, {"pdfplumber": fake}),
        patch.object(PDFLoader, "_ocr_page", render),
    ):
        return loader.load(Path("scan.pdf"))


def test_page_label_only_page_is_ocred():
    # The real-world case: pdfplumber returns "01\n100_11 Page 1" for a scan.
    ocr = _FakeOCR()
    doc = _load(["01\n100_11 Page 1"], ocr)
    assert ocr.calls == 1, "a page with only a label must still be treated as a scan"
    assert "actual scanned body" in doc.content
    assert doc.metadata["ocr_pages"] == 1


def test_real_text_page_is_not_ocred():
    ocr = _FakeOCR()
    doc = _load(["x" * 500], ocr)
    assert ocr.calls == 0, "a page with a real text layer must not pay for OCR"
    assert doc.metadata["ocr_pages"] == 0


def test_empty_page_is_ocred():
    ocr = _FakeOCR()
    _load([""], ocr)
    assert ocr.calls == 1


def test_failed_ocr_does_not_destroy_the_existing_text():
    # _ocr_page returns "" when page rendering fails; a page label beats nothing.
    ocr = _FakeOCR(result="")
    doc = _load(["01\n100_11 Page 1"], ocr)
    assert "100_11 Page 1" in doc.content
    assert doc.metadata["ocr_pages"] == 0


def test_threshold_zero_restores_empty_only_behaviour():
    ocr = _FakeOCR()
    _load(["01\n100_11 Page 1"], ocr, min_text_chars=0)
    assert ocr.calls == 0


def test_no_ocr_engine_configured_still_loads():
    doc = _load(["01\nPage 1"], None)
    assert "Page 1" in doc.content


def test_mixed_document_only_ocrs_the_scanned_pages():
    ocr = _FakeOCR()
    doc = _load(["y" * 400, "02\nPage 2", "z" * 300], ocr)
    assert ocr.calls == 1
    assert doc.metadata["pages"] == 3
    assert doc.metadata["ocr_pages"] == 1
