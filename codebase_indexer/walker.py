from __future__ import annotations
import os
import sys
from pathlib import Path
from typing import Iterator

_tools_root = Path(__file__).parent.parent
if str(_tools_root) not in sys.path:
    sys.path.insert(0, str(_tools_root))

from shared.walker import ExclusionRules

_BINARY_PEEK = 8192


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return b"\x00" in fh.read(_BINARY_PEEK)
    except OSError:
        return True


class RepoWalker:
    """
    Walks a directory tree yielding parseable files.

    Exclusion priority:
      1. Hard excludes (shared list)
      2. .gitignore patterns
      3. .indexignore patterns
      4. extra_excludes globs
    Files that exceed max_file_size_kb are added to skipped_files.
    Binary files (null bytes in first 8 KB) are silently skipped.
    """

    def __init__(
        self,
        root: Path,
        extra_excludes: list[str] | None = None,
        respect_gitignore: bool = True,
        max_file_size_kb: int = 500,
        include_extensions: list[str] | None = None,
    ):
        self._root = root
        self._max_bytes = max_file_size_kb * 1024
        self._include_ext: frozenset[str] | None = (
            frozenset(
                e.lower() if e.startswith(".") else f".{e.lower()}"
                for e in include_extensions
            )
            if include_extensions else None
        )
        self._rules = ExclusionRules(
            root=root,
            respect_gitignore=respect_gitignore,
            ignore_filename=".indexignore",
            extra_patterns=extra_excludes,
        )
        self._skipped: list[str] = []

    @property
    def skipped_files(self) -> list[str]:
        return self._skipped

    def walk(self) -> Iterator[Path]:
        for dirpath, dirnames, filenames in os.walk(self._root, topdown=True):
            current = Path(dirpath)
            dirnames[:] = sorted(
                d for d in dirnames
                if not self._rules.is_excluded(current / d)
            )
            for fname in sorted(filenames):
                fpath = current / fname
                if self._rules.is_excluded(fpath):
                    continue
                if self._include_ext is not None and fpath.suffix.lower() not in self._include_ext:
                    continue
                try:
                    size = fpath.stat().st_size
                except OSError as exc:
                    print(f"Warning: cannot stat {fpath}: {exc}", file=sys.stderr)
                    continue
                if size > self._max_bytes:
                    rel = str(fpath.relative_to(self._root))
                    self._skipped.append(f"{rel} (too large: {size // 1024} KB)")
                    continue
                if _is_binary(fpath):
                    continue
                yield fpath
