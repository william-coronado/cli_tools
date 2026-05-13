from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path

from ..indexer import FileIndex


class BaseParser(ABC):
    @abstractmethod
    def can_parse(self, path: Path) -> bool:
        """Return True if this parser handles the given file."""
        ...

    @abstractmethod
    def parse(self, path: Path, root: Path) -> FileIndex:
        """
        Parse the file and return a FileIndex.
        Must not raise — catch all errors and set parse_error instead.
        """
        ...
