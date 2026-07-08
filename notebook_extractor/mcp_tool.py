"""MCP handler for notebook_extractor. Exposed via the unified server (mcp_server.py)."""
from __future__ import annotations


def _handle(params: dict) -> str:
    from .extractor import NotebookExtractor, ExtractorOptions

    def _parse_slice(s):
        if s is None:
            return None
        if ":" not in s:
            idx = int(s)
            return slice(idx, idx + 1)
        parts = s.split(":", 1)
        return slice(int(parts[0]) if parts[0] else None,
                     int(parts[1]) if parts[1] else None)

    opts = ExtractorOptions(
        cells_slice=_parse_slice(params.get("cells")),
        code_only=bool(params.get("code_only", False)),
        markdown_only=bool(params.get("markdown_only", False)),
        tags=params.get("tags"),
        no_outputs=bool(params.get("no_outputs", False)),
        max_output_lines=int(params.get("max_output_lines", 30)),
    )
    result = NotebookExtractor(opts).extract(params["path"])
    return result.to_markdown()
