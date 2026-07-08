"""MCP handler for data_summarizer. Exposed via the unified server (mcp_server.py)."""
from __future__ import annotations


def _handle(params: dict) -> str:
    from .summarizer import DataSummarizer, SummarizerOptions

    path = params["path"]
    opts = SummarizerOptions(
        sample_head=int(params.get("sample", 5)),
        sample_tail=int(params.get("sample", 5)),
        no_stats=bool(params.get("no_stats", False)),
        max_rows=int(params.get("max_rows", 100_000)),
        columns=params.get("columns"),
        tables=[params["table"]] if params.get("table") else None,
        format_hint=params.get("format_hint"),
    )
    result = DataSummarizer(opts).summarize(path)
    return result.to_markdown()
