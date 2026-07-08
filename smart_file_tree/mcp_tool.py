"""MCP handler for smart_file_tree. Exposed via the unified server (mcp_server.py)."""
from __future__ import annotations

from pathlib import Path


def _handle_call(params: dict) -> str:
    import fnmatch
    import re
    import time as _time
    from .tree import build
    from .renderer import Renderer

    root = Path(params.get("path") or ".").resolve()
    if not root.is_dir():
        return f"error: not a directory: {root}"

    depth = params.get("depth")
    fmt = params.get("format", "tree")
    focus_str = params.get("focus")
    modified_after_str = params.get("modified_after")
    extra_excludes = params.get("exclude_patterns") or None
    include_ext = params.get("include_extensions") or None

    # Resolve focus
    focus_path: Path | None = None
    force_compact = False
    glob_pattern: str | None = None

    if focus_str:
        if any(c in focus_str for c in ("*", "?", "[")):
            force_compact = True
            glob_pattern = focus_str
        else:
            candidate = root / focus_str
            if candidate.is_dir():
                focus_path = candidate

    if force_compact:
        fmt = "compact"

    modified_after: float | None = None
    if modified_after_str:
        m = re.match(r"^(\d+)(m|h|d|w|mo|y)$", modified_after_str.strip())
        if m:
            n = int(m.group(1))
            unit = m.group(2)
            secs = {"m": 60, "h": 3600, "d": 86400, "w": 604800, "mo": 2_592_000, "y": 31_536_000}[unit]
            modified_after = _time.time() - n * secs

    result = build(
        root,
        max_depth=depth,
        focus_path=focus_path,
        extra_excludes=extra_excludes,
        include_extensions=include_ext,
        modified_after=modified_after,
    )

    if glob_pattern:
        result.nodes = [
            n for n in result.nodes
            if n.is_dir or fnmatch.fnmatch(str(n.rel_path), glob_pattern)
        ]

    return Renderer(use_ansi=False).render(result, fmt=fmt)
