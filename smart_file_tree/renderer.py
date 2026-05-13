from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path
from .tree import TreeNode, TreeResult


class Renderer:
    def __init__(self, use_ansi: bool | None = None):
        if use_ansi is None:
            self._ansi = sys.stdout.isatty()
        else:
            self._ansi = use_ansi

    def render(self, result: TreeResult, fmt: str, sort: str = "age", no_summary: bool = False) -> str:
        if fmt == "json":
            return self._render_json(result)
        if fmt == "compact":
            return self._render_compact(result, sort=sort, no_summary=no_summary)
        return self._render_tree(result, no_summary=no_summary)

    # ── JSON ──────────────────────────────────────────────────────────────────

    def _render_json(self, result: TreeResult) -> str:
        def node_dict(n: TreeNode) -> dict:
            d: dict = {
                "name": n.name,
                "rel_path": str(n.rel_path),
                "is_dir": n.is_dir,
                "depth": n.depth,
            }
            if n.is_dir:
                d["child_count"] = n.child_count
                d["dir_size_human"] = n.dir_size_human
            else:
                ann = n.annotation
                if ann:
                    d["annotation"] = {
                        "size_bytes": ann.size_bytes,
                        "size_human": ann.size_human,
                        "modified_ago": ann.modified_ago,
                        "modified_timestamp": ann.modified_timestamp,
                        "language": ann.language,
                        "is_binary": ann.is_binary,
                        "is_empty": ann.is_empty,
                        "is_large": ann.is_large,
                        "flags": ann.flags,
                    }
            return d

        payload = {
            "root_path": result.root_path,
            "generated_at": result.generated_at,
            "total_files": result.total_files,
            "total_dirs": result.total_dirs,
            "total_size_human": result.total_size_human,
            "skipped_count": result.skipped_count,
            "languages": result.languages,
            "recent_files": result.recent_files,
            "large_files": result.large_files,
            "nodes": [node_dict(n) for n in result.nodes],
        }
        return json.dumps(payload, indent=2)

    # ── Compact ───────────────────────────────────────────────────────────────

    def _render_compact(self, result: TreeResult, sort: str = "age", no_summary: bool = False) -> str:
        root_name = Path(result.root_path).name
        lines = [f"# {root_name} — {result.total_files} files · {result.total_size_human}", ""]

        file_nodes = [n for n in result.nodes if not n.is_dir and n.annotation]

        if sort == "age":
            file_nodes.sort(key=lambda n: -(n.annotation.modified_timestamp))  # type: ignore[union-attr]
        elif sort == "size":
            file_nodes.sort(key=lambda n: -(n.annotation.size_bytes))  # type: ignore[union-attr]
        else:
            file_nodes.sort(key=lambda n: str(n.rel_path).lower())

        if not file_nodes:
            lines.append("(no files)")
            return "\n".join(lines)

        max_path = max(len(str(n.rel_path)) for n in file_nodes)
        max_lang = max((len(n.annotation.language or "—") for n in file_nodes), default=1)
        lang_width = max(max_lang, 8)

        for n in file_nodes:
            ann = n.annotation
            assert ann is not None
            path_str = str(n.rel_path).ljust(max_path)
            size_str = ann.size_human.rjust(8)
            lang_str = (ann.language or "—").ljust(lang_width)
            age_str = ann.modified_ago.rjust(5)
            flag_str = "  " + "  ".join(f"[{f}]" for f in ann.flags) if ann.flags else ""
            lines.append(f"{path_str}  {size_str}  {lang_str}  {age_str}{flag_str}")

        if not no_summary:
            lines.append("")
            lines.extend(self._summary_lines(result))

        return "\n".join(lines)

    # ── Tree ──────────────────────────────────────────────────────────────────

    def _render_tree(self, result: TreeResult, no_summary: bool = False) -> str:
        nodes = result.nodes
        root_name = Path(result.root_path).name
        lines = [f"{root_name}/  ({result.total_files} files · {result.total_size_human})"]

        if not nodes:
            if not no_summary:
                lines.append("")
                lines.extend(self._summary_lines(result))
            return "\n".join(lines)

        # Per-depth max name widths (for alignment)
        max_name_by_depth: dict[int, int] = defaultdict(int)
        for n in nodes:
            if not n.is_dir:
                max_name_by_depth[n.depth] = max(max_name_by_depth[n.depth], len(n.name))

        # Max language string width across all file nodes
        max_lang = max(
            (len(n.annotation.language or "—") for n in nodes if not n.is_dir and n.annotation),
            default=6,
        )
        lang_width = max(max_lang, 6)

        is_last = self._compute_is_last(nodes)
        last_at_depth: dict[int, bool] = {}

        for i, node in enumerate(nodes):
            d = node.depth
            node_is_last = is_last[i]
            last_at_depth[d] = node_is_last

            prefix = self._prefix(d, node_is_last, last_at_depth)

            if node.is_dir:
                suffix = ""
                if node.child_count == -1:
                    suffix = "  [permission denied]"
                elif node.child_count is not None and (
                    self._was_depth_limited(node, nodes, i)
                ):
                    suffix = f"  ({node.child_count} files, not shown)"
                elif node.child_count == 0:
                    suffix = "  (empty)"
                lines.append(f"{prefix}{node.name}/{suffix}")
            else:
                ann = node.annotation
                if ann is None:
                    lines.append(f"{prefix}{node.name}")
                    continue

                max_name = max_name_by_depth.get(d, len(node.name))
                name_padded = node.name.ljust(max_name)
                size_str = ann.size_human.rjust(7)
                lang_str = (ann.language or "—").ljust(lang_width)
                age_str = ann.modified_ago.rjust(5)
                flag_str = "  " + "  ".join(f"[{f}]" for f in ann.flags) if ann.flags else ""
                lines.append(f"{prefix}{name_padded}   {size_str}  {lang_str}  {age_str}{flag_str}")

        if not no_summary:
            lines.append("")
            lines.extend(self._summary_lines(result))

        return "\n".join(lines)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _prefix(self, depth: int, is_last: bool, last_at_depth: dict[int, bool]) -> str:
        if depth == 0:
            return ""
        parts: list[str] = []
        for level in range(depth - 1):
            if last_at_depth.get(level, False):
                parts.append("    ")
            else:
                parts.append("│   ")
        parts.append("└── " if is_last else "├── ")
        return "".join(parts)

    def _compute_is_last(self, nodes: list[TreeNode]) -> list[bool]:
        by_parent: dict[str, list[int]] = defaultdict(list)
        for i, node in enumerate(nodes):
            by_parent[str(node.path.parent)].append(i)
        is_last = [False] * len(nodes)
        for indices in by_parent.values():
            if indices:
                is_last[indices[-1]] = True
        return is_last

    def _was_depth_limited(self, dir_node: TreeNode, nodes: list[TreeNode], idx: int) -> bool:
        """True if this directory's children were not expanded due to depth limit."""
        if idx + 1 >= len(nodes):
            return True
        next_node = nodes[idx + 1]
        return next_node.depth <= dir_node.depth

    def _summary_lines(self, result: TreeResult) -> list[str]:
        lines = ["---", "**Summary**"]
        lines.append(
            f"- Total: {result.total_files} files · {result.total_dirs} dirs · {result.total_size_human}"
        )
        lines.append(f"- Skipped: {result.skipped_count} files (excluded by rules)")

        if result.languages:
            lang_parts = ", ".join(f"{lang} ({count})" for lang, count in result.languages.items())
            lines.append(f"- Languages: {lang_parts}")

        if result.recent_files:
            lines.append(f"- Recently modified (last 7d): {', '.join(result.recent_files)}")

        if result.large_files:
            lines.append(f"- Large files (> 1 MB): {', '.join(result.large_files)}")

        return lines
