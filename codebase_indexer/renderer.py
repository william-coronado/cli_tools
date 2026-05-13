from __future__ import annotations
import dataclasses
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .indexer import CodebaseIndex, FileIndex

_OUTLINE_MAX_LINE = 100


# ── Outline ───────────────────────────────────────────────────────────────────

def render_outline(index: "CodebaseIndex") -> str:
    root_name = Path(index.root_path).name
    total_lines_str = _compact_num(index.total_lines)
    header = f"{root_name}/ ({index.total_files} files, {total_lines_str} lines)"

    tree = _build_path_tree(index.files)
    lines: list[str] = [header]
    _render_tree_node(tree, "", lines)
    return "\n".join(lines)


def _compact_num(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _build_path_tree(files: list) -> dict:
    tree: dict = {}
    for f in files:
        parts = Path(f.path).parts
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = f
    return tree


def _render_tree_node(node: dict, prefix: str, lines: list[str]) -> None:
    dirs = sorted(k for k, v in node.items() if isinstance(v, dict))
    files = sorted(k for k, v in node.items() if not isinstance(v, dict))
    entries = dirs + files

    for i, key in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        child_prefix = prefix + ("    " if is_last else "│   ")
        value = node[key]

        if isinstance(value, dict):
            line = f"{prefix}{connector}{key}/"
        else:
            annotation = _file_annotation(value)
            line = f"{prefix}{connector}{key}{annotation}"

        if len(line) > _OUTLINE_MAX_LINE:
            line = line[:_OUTLINE_MAX_LINE - 3] + "..."
        lines.append(line)

        if isinstance(value, dict):
            _render_tree_node(value, child_prefix, lines)


def _file_annotation(f: "FileIndex") -> str:
    items: list[str] = []
    for cls in f.classes[:3]:
        if cls.methods:
            method_names = ", ".join(m.name for m in cls.methods[:5])
            items.append(f"{cls.name}: {method_names}")
        else:
            items.append(cls.name)
    for func in f.functions[:3]:
        items.append(func.name)
    if not items:
        return ""
    return " [" + ", ".join(items) + "]"


# ── Markdown ──────────────────────────────────────────────────────────────────

def render_markdown(index: "CodebaseIndex", detail: str = "normal") -> str:
    root_name = Path(index.root_path).name
    lines: list[str] = []

    lines.append(f"# Codebase Index: {root_name}")
    lines.append("")

    token_str = f" | **Est. tokens:** ~{index.estimated_tokens:,}" if index.estimated_tokens else ""
    lines.append(
        f"**Generated:** {index.generated_at}  \n"
        f"**Files:** {index.total_files:,} | **Lines:** {index.total_lines:,}{token_str}"
    )
    lines.append("")

    if index.languages:
        lines.append("## Languages")
        lines.append("")
        lines.append("| Language | Files |")
        lines.append("|----------|-------|")
        for lang, count in sorted(index.languages.items(), key=lambda x: -x[1]):
            lines.append(f"| {lang.title()} | {count} |")
        lines.append("")

    lines.append("---")
    lines.append("")

    for f in index.files:
        _render_file_markdown(f, lines, detail)

    return "\n".join(lines)


def _render_file_markdown(f: "FileIndex", lines: list[str], detail: str) -> None:
    size_str = _human_size(f.size_bytes)
    lines.append(f"## {f.path}")
    lines.append(f"*{f.language.title()} · {f.line_count:,} lines · {size_str}*")
    lines.append("")

    if f.parse_error:
        lines.append(f"> **Parse error:** {f.parse_error}")
        lines.append("")

    if detail == "low":
        if f.classes:
            lines.append("**Classes:** " + ", ".join(f"`{c.name}`" for c in f.classes))
            lines.append("")
        lines.append("---")
        lines.append("")
        return

    # normal or high

    if f.imports:
        modules: list[str] = []
        seen: set[str] = set()
        for imp in f.imports:
            top = imp.module.lstrip(".").split(".")[0] if imp.module else ""
            if top and top not in seen:
                seen.add(top)
                modules.append(f"`{top}`")
        if modules:
            lines.append("**Imports:** " + ", ".join(modules))
            lines.append("")

    if f.classes:
        lines.append("**Classes:**")
        lines.append("")
        for cls in f.classes:
            bases_str = f"({', '.join(cls.bases)})" if cls.bases else ""
            lines.append(f"### `{cls.name}{bases_str}`")

            if detail == "high" and cls.decorators:
                lines.append("")
                for dec in cls.decorators:
                    lines.append(f"*{dec}*")

            if cls.docstring:
                doc = cls.docstring if detail == "high" else cls.docstring.splitlines()[0]
                lines.append("")
                lines.append(f"> {doc}")

            if cls.methods:
                lines.append("")
                lines.append("| Method | Signature |")
                lines.append("|--------|-----------|")
                for m in cls.methods:
                    sig = m.signature.replace("|", "\\|")
                    lines.append(f"| `{m.name}` | `{sig}` |")

                if detail == "high":
                    for m in cls.methods:
                        if m.docstring:
                            lines.append("")
                            lines.append(f"**`{m.name}`:** {m.docstring}")
                        if m.decorators:
                            lines.append("")
                            lines.append("*" + " ".join(m.decorators) + "*")

            lines.append("")

    if f.functions:
        lines.append("**Functions:**")
        lines.append("")
        lines.append("| Function | Signature |")
        lines.append("|----------|-----------|")
        for func in f.functions:
            sig = func.signature.replace("|", "\\|")
            lines.append(f"| `{func.name}` | `{sig}` |")

        if detail == "high":
            for func in f.functions:
                if func.docstring:
                    lines.append("")
                    lines.append(f"**`{func.name}`:** {func.docstring}")
                if func.decorators:
                    lines.append("")
                    lines.append("*" + " ".join(func.decorators) + "*")
        lines.append("")

    if detail == "high" and f.constants:
        lines.append("**Constants:** " + ", ".join(f"`{c}`" for c in f.constants))
        lines.append("")

    lines.append("---")
    lines.append("")


def _human_size(n: int) -> str:
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    if n >= 1_024:
        return f"{n / 1_024:.1f} KB"
    return f"{n} B"


# ── JSON ──────────────────────────────────────────────────────────────────────

def render_json(index: "CodebaseIndex") -> dict:
    return dataclasses.asdict(index)
