from __future__ import annotations
from pathlib import Path
import pathspec

HARD_EXCLUDES = [
    ".git", ".hg", ".svn",
    "__pycache__", "*.pyc", "*.pyo", "*.pyd",
    ".venv", "venv", "env", ".env",
    "node_modules", ".pnp",
    "dist", "build", "target", "_build", "site",
    "*.egg-info", ".eggs",
    ".tox", ".nox", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".DS_Store", "Thumbs.db",
    "*.min.js", "*.min.css",
    "*.lock",
    "*.map",
    "coverage", ".coverage", "htmlcov",
]


class ExclusionRules:
    def __init__(
        self,
        root: Path,
        respect_gitignore: bool = True,
        ignore_filename: str = ".treeignore",
        extra_patterns: list[str] | None = None,
    ):
        self._root = root

        hard_patterns = list(HARD_EXCLUDES)
        if extra_patterns:
            hard_patterns.extend(extra_patterns)
        self._hard_spec = pathspec.PathSpec.from_lines("gitignore", hard_patterns)

        dynamic_patterns: list[str] = []
        if respect_gitignore:
            gitignore = root / ".gitignore"
            if gitignore.is_file():
                for line in gitignore.read_text(errors="replace").splitlines():
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        dynamic_patterns.append(stripped)

        tool_ignore = root / ignore_filename
        if tool_ignore.is_file():
            for line in tool_ignore.read_text(errors="replace").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    dynamic_patterns.append(stripped)

        self._dynamic_spec: pathspec.PathSpec | None = (
            pathspec.PathSpec.from_lines("gitignore", dynamic_patterns)
            if dynamic_patterns
            else None
        )

    def is_excluded(self, path: Path) -> bool:
        name = path.name
        if self._hard_spec.match_file(name):
            return True

        try:
            rel = str(path.relative_to(self._root))
        except ValueError:
            rel = name

        if self._hard_spec.match_file(rel):
            return True
        if self._dynamic_spec and self._dynamic_spec.match_file(rel):
            return True
        return False
