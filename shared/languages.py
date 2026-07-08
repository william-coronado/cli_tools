"""Extension → language mapping shared across tools.

Used by codebase_indexer's generic parser and smart_file_tree's annotator as
the fallback when pygments is unavailable (or has no lexer for the file).
"""
from __future__ import annotations

EXT_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python", ".pyi": "python",
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


def language_for_extension(ext: str) -> str | None:
    """Return the language for a file extension (with leading dot), or None."""
    return EXT_LANGUAGE_MAP.get(ext.lower())
