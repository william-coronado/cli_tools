from __future__ import annotations

import json
import sys


TOOL_DEFINITIONS = [
    {
        "name": "inspect_http",
        "description": (
            "Make an HTTP request and return a token-efficient summary: status code, "
            "selected response headers, and a shape + sample of the response body. "
            "JSON responses show a schema + N sample records. Text is truncated. "
            "Use instead of curl when you care about structure, not raw bytes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url":              {"type": "string"},
                "method":           {"type": "string", "description": "HTTP method (default GET)"},
                "headers":          {"type": "array", "items": {"type": "string"},
                                     "description": 'Headers as ["Name: Value", ...]'},
                "data":             {"type": "string", "description": "Request body string"},
                "content_type":     {"type": "string"},
                "max_array_items":  {"type": "integer"},
                "shape_only":       {"type": "boolean"},
                "no_redact_cookies":{"type": "boolean"},
                "show_all_headers": {"type": "boolean"},
                "timeout":          {"type": "number"},
            },
            "required": ["url"],
        },
    }
]


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


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            name = request.get("name")
            params = request.get("parameters", {})
            if name == "inspect_http":
                result = _handle(params)
            else:
                print(json.dumps({"error": f"Unknown tool: {name}"}), flush=True)
                continue
            response = {"result": result}
        except Exception as e:
            response = {"error": str(e)}
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
