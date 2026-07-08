"""MCP handler for log_summarizer. Exposed via the unified server (mcp_server.py)."""
from __future__ import annotations


def _handle(params: dict) -> str:
    from pathlib import Path
    from .summarizer import LogSummarizer

    path = params["path"]
    format_hint = params.get("format_hint")
    errors_only = bool(params.get("errors_only", False))
    tail = params.get("tail")

    summarizer = LogSummarizer(format_hint=format_hint, errors_only=errors_only)

    if tail:
        from collections import deque
        with open(path, "rb") as f:
            buf: deque = deque(maxlen=tail)
            for line in f:
                buf.append(line)
        result = summarizer.summarize(iter(buf))
    else:
        result = summarizer.summarize(Path(path))

    return result.to_markdown()
