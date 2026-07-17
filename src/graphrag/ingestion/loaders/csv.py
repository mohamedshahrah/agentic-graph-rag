"""CSV/TSV loader. Each row becomes a "header: value" sentence block, which
embeds far better than a raw comma grid — a retrieved chunk then reads as
"name: Widget; price: 12.50" instead of an unlabeled value soup."""

from __future__ import annotations

import csv
from pathlib import Path

from graphrag.core.types import Document
from graphrag.ingestion.loaders.base import Loader

_MAX_ROWS = 5000  # a hard stop so a database dump doesn't become one document


class CSVLoader(Loader):
    suffixes = (".csv", ".tsv")

    def load(self, path: Path) -> Document:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        blocks: list[str] = []
        with path.open(encoding="utf-8", errors="ignore", newline="") as fh:
            reader = csv.reader(fh, delimiter=delimiter)
            header = next(reader, None) or []
            for i, row in enumerate(reader):
                if i >= _MAX_ROWS:
                    break
                pairs = [
                    f"{(header[j].strip() if j < len(header) else f'col{j + 1}')}: {cell.strip()}"
                    for j, cell in enumerate(row)
                    if cell.strip()
                ]
                if pairs:
                    blocks.append("; ".join(pairs))
        return Document(
            source=str(path),
            content="\n\n".join(blocks),
            metadata={"type": "csv", "rows": len(blocks)},
        )
