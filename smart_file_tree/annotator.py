from __future__ import annotations
import time
from pathlib import Path
from .tree import TreeNode, FileAnnotation


class FileAnnotator:
    LARGE_FILE_BYTES = 1_048_576
    RECENT_WINDOW_SECONDS = 86_400 * 7
    BINARY_SAMPLE_BYTES = 8_192

    def __init__(
        self,
        large_file_threshold: int = LARGE_FILE_BYTES,
        recent_window_seconds: int = RECENT_WINDOW_SECONDS,
        now: float | None = None,
    ):
        self._large_threshold = large_file_threshold
        self._recent_window = recent_window_seconds
        self._now = now if now is not None else time.time()

    def annotate(self, node: TreeNode) -> FileAnnotation:
        try:
            stat = node.path.stat()
            size_bytes = stat.st_size
            mtime = stat.st_mtime
        except OSError:
            size_bytes = 0
            mtime = 0.0

        is_binary = self._is_binary(node.path)
        is_empty = size_bytes == 0
        is_large = size_bytes > self._large_threshold
        language = None if is_binary else self._detect_language(node.path)

        return FileAnnotation(
            size_bytes=size_bytes,
            size_human=self._human_size(size_bytes),
            modified_ago=self._modified_ago(mtime),
            modified_timestamp=mtime,
            language=language,
            is_binary=is_binary,
            is_empty=is_empty,
            is_large=is_large,
            flags=self._build_flags(size_bytes, mtime, is_binary, is_empty),
        )

    def annotate_directory(self, node: TreeNode, children: list[TreeNode]) -> None:
        total_bytes = 0
        count = 0
        for child in children:
            if child.is_dir:
                count += child.child_count or 0
            else:
                count += 1
                if child.annotation:
                    total_bytes += child.annotation.size_bytes
        node.child_count = count
        node.dir_size_human = self._human_size(total_bytes)

    def _human_size(self, size_bytes: int) -> str:
        if size_bytes == 0:
            return "0 B"
        for unit, factor in [("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)]:
            if size_bytes >= factor:
                return f"{size_bytes / factor:.1f} {unit}"
        return f"{size_bytes} B"

    def _modified_ago(self, mtime: float) -> str:
        delta = self._now - mtime
        if delta < 60:
            return "just now"
        if delta < 3_600:
            return f"{int(delta / 60)}m"
        if delta < 86_400:
            return f"{int(delta / 3_600)}h"
        if delta < 86_400 * 7:
            return f"{int(delta / 86_400)}d"
        if delta < 86_400 * 28:
            return f"{int(delta / (86_400 * 7))}w"
        if delta < 86_400 * 365:
            return f"{int(delta / (86_400 * 30))}mo"
        return f"{int(delta / (86_400 * 365))}y"

    def _detect_language(self, path: Path) -> str | None:
        try:
            from pygments.lexers import get_lexer_for_filename
            lexer = get_lexer_for_filename(path.name)
            name = lexer.name
            if name in ("Text only", "Plain Text", "Generic", "Binary"):
                return None
            return name
        except Exception:
            pass
        # Extension-map fallback when pygments is missing or has no lexer
        try:
            from shared.languages import language_for_extension
            return language_for_extension(path.suffix)
        except ImportError:
            return None

    def _is_binary(self, path: Path) -> bool:
        try:
            with open(path, "rb") as f:
                chunk = f.read(self.BINARY_SAMPLE_BYTES)
            return b"\x00" in chunk
        except OSError:
            return False

    def _build_flags(
        self,
        size_bytes: int,
        mtime: float,
        is_binary: bool,
        is_empty: bool,
    ) -> list[str]:
        flags: list[str] = []
        if is_binary:
            flags.append("binary")
        if is_empty:
            flags.append("empty")
        if size_bytes > self._large_threshold:
            flags.append("large")
        if (self._now - mtime) <= self._recent_window:
            flags.append("recent")
        return flags
