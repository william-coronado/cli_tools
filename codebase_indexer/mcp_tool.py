"""MCP handler for codebase_indexer. Exposed via the unified server (mcp_server.py)."""
from __future__ import annotations


def _handle_index_codebase(params: dict) -> str:
    import json as _json
    from pathlib import Path
    from .indexer import CodebaseIndexer

    repo_path = params.get("repo_path", ".")
    detail = params.get("detail", "normal")
    fmt = params.get("format", "markdown")
    include_ext = params.get("include_extensions")
    excludes = params.get("exclude_patterns")

    indexer = CodebaseIndexer(
        root=Path(repo_path).resolve(),
        extra_excludes=excludes,
        include_extensions=include_ext,
        show_progress=False,
    )
    index = indexer.build()

    if fmt == "outline":
        return index.to_outline()
    if fmt == "json":
        return _json.dumps(index.to_json(), indent=2, default=str)
    return index.to_markdown(detail=detail)
