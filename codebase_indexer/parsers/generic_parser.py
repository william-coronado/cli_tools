from __future__ import annotations
from pathlib import Path

from .base import BaseParser
from ..indexer import FileIndex

_EXT_MAP: dict[str, str] = {
    ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".go": "go", ".rs": "rust", ".java": "java",
    ".cs": "c#", ".cpp": "c++", ".c": "c", ".h": "c",
    ".rb": "ruby", ".php": "php", ".swift": "swift", ".kt": "kotlin",
    ".md": "markdown", ".rst": "restructuredtext",
    ".txt": "text", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".json": "json",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".sql": "sql", ".html": "html", ".css": "css", ".scss": "scss",
}

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
            text = path.read_text(encoding="utf-8", errors="replace")
            line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
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
