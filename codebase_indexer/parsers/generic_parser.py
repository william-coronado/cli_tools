from __future__ import annotations
from pathlib import Path

from .base import BaseParser
from ..indexer import FileIndex
from shared.languages import EXT_LANGUAGE_MAP as _EXT_MAP

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(_EXT_MAP)


def _detect_language(path: Path) -> str:
    ext = path.suffix.lower()
    try:
        from pygments.lexers import get_lexer_for_filename
        from pygments.util import ClassNotFound
        try:
            return get_lexer_for_filename(path.name).name.lower()
        except ClassNotFound:
            pass
    except ImportError:
        pass
    return _EXT_MAP.get(ext, "unknown")


class GenericParser(BaseParser):
    """Metadata-only parser for non-Python file types."""

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() in SUPPORTED_EXTENSIONS

    def parse(self, path: Path, root: Path) -> FileIndex:
        rel = str(path.relative_to(root))
        try:
            size = path.stat().st_size
            line_count = 0
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for _ in f:
                    line_count += 1
        except OSError as exc:
            return FileIndex(
                path=rel, language=_detect_language(path),
                line_count=0, size_bytes=0,
                imports=[], functions=[], classes=[], constants=[],
                parse_error=str(exc),
            )

        return FileIndex(
            path=rel,
            language=_detect_language(path),
            line_count=line_count,
            size_bytes=size,
            imports=[],
            functions=[],
            classes=[],
            constants=[],
            parse_error=None,
        )
