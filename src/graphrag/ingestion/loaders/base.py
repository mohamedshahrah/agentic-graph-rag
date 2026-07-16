"""Document loaders. Each loader turns a file into a `Document` (plain text +
metadata). Images and scanned pages go through OCR first."""

from __future__ import annotations

import abc
from pathlib import Path

from graphrag.core.types import Document


class Loader(abc.ABC):
    #: File suffixes this loader handles, lower-case incl. dot.
    suffixes: tuple[str, ...] = ()

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.suffixes

    @abc.abstractmethod
    def load(self, path: Path) -> Document:
        ...
