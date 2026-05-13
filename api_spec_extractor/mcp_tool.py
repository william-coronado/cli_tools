from __future__ import annotations

import json
import sys


TOOL_DEFINITIONS = [
    {
        "name": "extract_api_spec",
        "description": (
            "Extract a catalog or detail view from an OpenAPI (2/3) or GraphQL SDL spec. "
            "Returns an endpoint table (default) or per-endpoint detail with parameters "
            "and response schemas (--detail). Use instead of reading raw spec files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source":             {"type": "string", "description": "File path or URL"},
                "endpoint":           {"type": "string", "description": "Filter paths by substring"},
                "method":             {"type": "string", "description": "Comma-separated HTTP methods"},
                "tag":                {"type": "string", "description": "Filter by OpenAPI tag"},
                "detail":             {"type": "boolean", "description": "Include params + schemas"},
                "include_deprecated": {"type": "boolean", "description": "Include deprecated endpoints"},
            },
            "required": ["source"],
        },
    }
]


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


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            name = request.get("name")
            params = request.get("parameters", {})
            if name == "extract_api_spec":
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
