"""MCP handler for inspect_image. Exposed via the unified server (mcp_server.py)."""
from __future__ import annotations


def _handle(params: dict) -> str:
    from .inspector import inspect_image
    info = inspect_image(params["path"])
    return info.to_markdown()
