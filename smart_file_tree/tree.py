from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone
import time


@dataclass
class FileAnnotation:
    size_bytes: int
    size_human: str
    modified_ago: str
    modified_timestamp: float
    language: str | None
    is_binary: bool
    is_empty: bool
    is_large: bool
    flags: list[str]


@dataclass
class TreeNode:
    name: str
    path: Path
    rel_path: Path
    is_dir: bool
    depth: int
    annotation: FileAnnotation | None
    children: list[TreeNode] = field(default_factory=list)
    is_excluded: bool = False
    child_count: int | None = None
    dir_size_human: str | None = None


@dataclass
class TreeResult:
    root_path: str
    generated_at: str
    total_files: int
    total_dirs: int
    total_size_human: str
    skipped_count: int
    languages: dict[str, int]
    recent_files: list[str]
    large_files: list[str]
    nodes: list[TreeNode]

    def to_markdown(self) -> str:
        from .renderer import Renderer
        return Renderer(use_ansi=False).render(self, "tree")

    def to_plain(self) -> str:
        from .renderer import Renderer
        return Renderer(use_ansi=False).render(self, "tree")

    def to_json(self) -> dict:
        import json
        from .renderer import Renderer
        return json.loads(Renderer(use_ansi=False).render(self, "json"))


def build(
    root: Path,
    *,
    respect_gitignore: bool = True,
    extra_excludes: list[str] | None = None,
    max_depth: int | None = None,
    focus_path: Path | None = None,
    modified_after: float | None = None,
    modified_before: float | None = None,
    min_size: int | None = None,
    max_size: int | None = None,
    include_extensions: list[str] | None = None,
    dirs_only: bool = False,
    files_only: bool = False,
    large_threshold: int = 1_048_576,
    recent_window: int = 86_400 * 7,
    sort: str = "alpha",
    show_hidden: bool = False,
) -> TreeResult:
    from .walker import TreeWalker
    from .annotator import FileAnnotator

    now = time.time()
    walker = TreeWalker(
        root=root,
        extra_excludes=extra_excludes,
        respect_gitignore=respect_gitignore,
        max_depth=max_depth,
        focus_path=focus_path,
        show_hidden=show_hidden,
    )
    annotator = FileAnnotator(
        large_file_threshold=large_threshold,
        recent_window_seconds=recent_window,
        now=now,
    )

    flat_nodes, skipped_count = walker.build_tree()

    for node in flat_nodes:
        if not node.is_dir:
            node.annotation = annotator.annotate(node)

    # Annotate directories bottom-up
    for dir_node in reversed([n for n in flat_nodes if n.is_dir]):
        direct_children = [n for n in flat_nodes if n.path.parent == dir_node.path]
        annotator.annotate_directory(dir_node, direct_children)

    # Post-walk filters
    norm_exts = [e.lower() if e.startswith(".") else f".{e.lower()}"
                 for e in (include_extensions or [])]

    def passes(node: TreeNode) -> bool:
        if node.is_dir:
            return not files_only
        if dirs_only:
            return False
        ann = node.annotation
        if ann is None:
            return True
        if modified_after is not None and ann.modified_timestamp < modified_after:
            return False
        if modified_before is not None and ann.modified_timestamp > modified_before:
            return False
        if min_size is not None and ann.size_bytes < min_size:
            return False
        if max_size is not None and ann.size_bytes > max_size:
            return False
        if norm_exts and node.path.suffix.lower() not in norm_exts:
            return False
        return True

    visible = [n for n in flat_nodes if passes(n)]

    file_nodes = [n for n in visible if not n.is_dir]
    total_bytes = sum(n.annotation.size_bytes for n in file_nodes if n.annotation)

    languages: dict[str, int] = {}
    recent_files: list[str] = []
    large_files: list[str] = []
    for n in file_nodes:
        ann = n.annotation
        if ann is None:
            continue
        if ann.language:
            languages[ann.language] = languages.get(ann.language, 0) + 1
        if "recent" in ann.flags:
            recent_files.append(str(n.rel_path))
        if "large" in ann.flags:
            large_files.append(f"{n.rel_path} ({ann.size_human})")

    return TreeResult(
        root_path=str(root),
        generated_at=datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        total_files=len(file_nodes),
        total_dirs=len([n for n in visible if n.is_dir]),
        total_size_human=annotator._human_size(total_bytes),
        skipped_count=skipped_count,
        languages=dict(sorted(languages.items(), key=lambda x: -x[1])),
        recent_files=recent_files,
        large_files=large_files,
        nodes=visible,
    )
