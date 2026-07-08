"""MCP handler for http_inspector. Exposed via the unified server (mcp_server.py)."""
from __future__ import annotations


def _handle(params: dict) -> str:
    from .inspector import HttpInspector, InspectorOptions

    raw_headers = params.get("headers") or []
    headers: list[tuple[str, str]] = []
    for h in raw_headers:
        if ":" in h:
            name, _, value = h.partition(":")
            headers.append((name.strip(), value.strip()))

    data = params.get("data")
    body = data.encode("utf-8") if data else None

    method = params.get("method")
    if method is None:
        method = "POST" if body is not None else "GET"

    opts = InspectorOptions(
        method=method,
        headers=headers,
        data=body,
        content_type=params.get("content_type"),
        max_array_items=int(params.get("max_array_items", 5)),
        shape_only=bool(params.get("shape_only", False)),
        no_redact_cookies=bool(params.get("no_redact_cookies", False)),
        show_all_headers=bool(params.get("show_all_headers", False)),
        timeout=float(params.get("timeout", 10.0)),
    )
    result = HttpInspector(opts).inspect(params["url"])
    return result.to_markdown()
