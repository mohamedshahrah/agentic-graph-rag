"""HTML loader: strips markup, scripts, and navigation chrome down to the text."""

from __future__ import annotations

import re
from pathlib import Path

from graphrag.core.errors import IngestionError
from graphrag.core.types import Document
from graphrag.ingestion.loaders.base import Loader

_BLANKS = re.compile(r"\n{3,}")


class HTMLLoader(Loader):
    suffixes = (".html", ".htm")

    def load(self, path: Path) -> Document:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:  # pragma: no cover
            raise IngestionError("beautifulsoup4 is not installed") from exc

        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
            tag.decompose()
        text = _BLANKS.sub("\n\n", soup.get_text("\n")).strip()
        title = soup.title.get_text().strip() if soup.title else ""
        if title:
            text = f"{title}\n\n{text}"
        return Document(
            source=str(path), content=text, metadata={"type": "html", "title": title}
        )
