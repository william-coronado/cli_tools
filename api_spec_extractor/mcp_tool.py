"""MCP handler for api_spec_extractor. Exposed via the unified server (mcp_server.py)."""
from __future__ import annotations


def _handle(params: dict) -> str:
    from .extractor import SpecExtractor, ExtractorOptions

    method_filter = None
    method_str = params.get("method")
    if method_str:
        method_filter = [m.strip().upper() for m in method_str.split(",") if m.strip()]

    opts = ExtractorOptions(
        endpoint_filter=params.get("endpoint"),
        method_filter=method_filter,
        tag_filter=params.get("tag"),
        detail=bool(params.get("detail", False)),
        include_deprecated=bool(params.get("include_deprecated", False)),
    )
    result = SpecExtractor(opts).extract(params["source"])
    return result.to_markdown()
