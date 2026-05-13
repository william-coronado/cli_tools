"""Minimal MCP stdio server exposing smart_file_tree as a tool."""
from __future__ import annotations
import json
import sys
from pathlib import Path

TOOL_DEFINITION = {
    "name": "smart_file_tree",
    "description": (
        "Generate an annotated file tree for a directory. Shows file sizes, ages, "
        "languages, and flags (large, binary, recently modified). Automatically "
        "excludes noise like node_modules, __pycache__, and build artifacts. "
        "Use before reading individual files to orient yourself in a codebase."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to walk. Defaults to current working directory.",
            },
            "depth": {
                "type": "integer",
                "description": "Maximum display depth. Omit for unlimited.",
            },
            "format": {
                "type": "string",
                "enum": ["tree", "compact", "json"],
                "description": "Output format. Default: tree.",
            },
            "focus": {
                "type": "string",
                "description": "Subdirectory or glob pattern to focus on.",
            },
            "modified_after": {
                "type": "string",
                "description": "Filter to files modified after this window, e.g. '7d', '24h'.",
            },
            "exclude_patterns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Additional glob patterns to exclude.",
            },
            "include_extensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Limit to files with these extensions, e.g. [\".py\", \".ts\"].",
            },
        },
        "required": [],
    },
}


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


def _send(msg: dict) -> None:
    line = json.dumps(msg)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def main() -> None:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")
        req_id = msg.get("id")

        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "smart_file_tree", "version": "1.0.0"},
            }})

        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": [TOOL_DEFINITION]}})

        elif method == "tools/call":
            tool_name = msg.get("params", {}).get("name")
            tool_input = msg.get("params", {}).get("arguments", {})
            if tool_name != "smart_file_tree":
                _send({"jsonrpc": "2.0", "id": req_id, "error": {
                    "code": -32601, "message": f"Unknown tool: {tool_name}",
                }})
                continue
            try:
                content = _handle_call(tool_input)
                _send({"jsonrpc": "2.0", "id": req_id, "result": {
                    "content": [{"type": "text", "text": content}],
                }})
            except Exception as exc:
                _send({"jsonrpc": "2.0", "id": req_id, "result": {
                    "content": [{"type": "text", "text": f"error: {exc}"}],
                    "isError": True,
                }})

        elif method == "notifications/initialized":
            pass  # no response needed

        else:
            if req_id is not None:
                _send({"jsonrpc": "2.0", "id": req_id, "error": {
                    "code": -32601, "message": f"Method not found: {method}",
                }})


if __name__ == "__main__":
    main()
