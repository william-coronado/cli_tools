from __future__ import annotations
import os
import sys
from pathlib import Path

# Make tools/ root importable so 'shared' package is found
_tools_root = Path(__file__).parent.parent
if str(_tools_root) not in sys.path:
    sys.path.insert(0, str(_tools_root))

from shared.walker import ExclusionRules
from .tree import TreeNode

_MAX_CHILDREN_DEFAULT = 50


class TreeWalker:
    def __init__(
        self,
        root: Path,
        extra_excludes: list[str] | None = None,
        respect_gitignore: bool = True,
        max_depth: int | None = None,
        focus_path: Path | None = None,
        max_children: int = _MAX_CHILDREN_DEFAULT,
    ):
        self._root = root
        self._max_depth = max_depth
        self._focus_path = focus_path
        self._max_children = max_children
        self._rules = ExclusionRules(
            root=root,
            respect_gitignore=respect_gitignore,
            ignore_filename=".treeignore",
            extra_patterns=extra_excludes,
        )

    def build_tree(self) -> tuple[list[TreeNode], int]:
        nodes: list[TreeNode] = []
        start = self._focus_path if self._focus_path else self._root
        skipped = self._walk(start, 0, nodes)
        return nodes, skipped

    def _walk(self, directory: Path, depth: int, nodes: list[TreeNode]) -> int:
        skipped = 0
        try:
            raw_entries = list(os.scandir(directory))
        except PermissionError:
            for node in nodes:
                if node.path == directory and node.is_dir:
                    node.child_count = -1  # sentinel for permission denied
            return 0

        entries = self._sort_entries(raw_entries)
        total = len(entries)
        shown = 0

        for entry in entries:
            path = Path(entry.path)

            if self._rules.is_excluded(path):
                skipped += 1
                continue

            is_symlink = entry.is_symlink()
            is_dir_entry = entry.is_dir(follow_symlinks=False)
            rel_path = path.relative_to(self._root)

            if is_symlink and is_dir_entry:
                skipped += 1
                continue

            if is_symlink:
                try:
                    target = os.readlink(path)
                    if not Path(target).exists():
                        display = f"{entry.name} [broken symlink]"
                    else:
                        display = f"{entry.name} → {target}"
                except OSError:
                    display = f"{entry.name} [broken symlink]"
                node = TreeNode(
                    name=display,
                    path=path,
                    rel_path=rel_path,
                    is_dir=False,
                    depth=depth,
                    annotation=None,
                )
                nodes.append(node)
                shown += 1
                continue

            if is_dir_entry:
                node = TreeNode(
                    name=entry.name,
                    path=path,
                    rel_path=rel_path,
                    is_dir=True,
                    depth=depth,
                    annotation=None,
                )
                nodes.append(node)
                shown += 1

                if self._max_depth is None or depth < self._max_depth:
                    skipped += self._walk(path, depth + 1, nodes)
                else:
                    try:
                        node.child_count = sum(1 for _ in os.scandir(path))
                    except PermissionError:
                        pass
            else:
                if shown >= self._max_children:
                    # Will add a sentinel; count remaining
                    remaining = sum(
                        1 for e in entries[entries.index(entry):]
                        if not self._rules.is_excluded(Path(e.path))
                    )
                    sentinel = TreeNode(
                        name=f"... (and {remaining} more files)",
                        path=directory / "...",
                        rel_path=directory.relative_to(self._root) / "...",
                        is_dir=False,
                        depth=depth,
                        annotation=None,
                    )
                    nodes.append(sentinel)
                    break

                node = TreeNode(
                    name=entry.name,
                    path=path,
                    rel_path=rel_path,
                    is_dir=False,
                    depth=depth,
                    annotation=None,
                )
                nodes.append(node)
                shown += 1

        return skipped

    def _sort_entries(self, entries: list[os.DirEntry]) -> list[os.DirEntry]:
        dirs = sorted(
            [e for e in entries if e.is_dir(follow_symlinks=False)],
            key=lambda e: e.name.lower(),
        )
        files = sorted(
            [e for e in entries if not e.is_dir(follow_symlinks=False)],
            key=lambda e: e.name.lower(),
        )
        return dirs + files
