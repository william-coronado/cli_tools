"""MCP handler for dep_inspector. Exposed via the unified server (mcp_server.py)."""
from __future__ import annotations


def _handle(params: dict) -> str:
    from .inspector import DepInspector, InspectorOptions

    opts = InspectorOptions(
        direct_only=bool(params.get("direct_only", False)),
        outdated=bool(params.get("outdated", False)),
        audit=bool(params.get("audit", False)),
        ecosystem=params.get("ecosystem"),
        include_dev=not bool(params.get("no_dev", False)),
        severity_filter=params.get("severity"),
    )
    result = DepInspector(opts).inspect(params["path"])
    return result.to_markdown()
