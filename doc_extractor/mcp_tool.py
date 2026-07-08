"""MCP handler for doc_extractor. Exposed via the unified server (mcp_server.py)."""
from __future__ import annotations


def _handle(params: dict) -> str:
    from .extractor import DocExtractor, ExtractorOptions

    opts = ExtractorOptions(max_chars=int(params.get("max_chars", 200_000)))
    result = DocExtractor(opts).extract(params["path"])
    return result.to_markdown()
