from __future__ import annotations

import json
import sys


TOOL_DEFINITIONS = [
    {
        "name": "extract_notebook",
        "description": (
            "Extract code and markdown from a Jupyter notebook (.ipynb). "
            "Strips base64 images, truncates long outputs, and deduplicates "
            "progress-bar streams. Use instead of reading raw .ipynb JSON."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path":             {"type": "string"},
                "cells":            {"type": "string", "description": 'Slice, e.g. "0:20"'},
                "code_only":        {"type": "boolean"},
                "markdown_only":    {"type": "boolean"},
                "tags":             {"type": "array", "items": {"type": "string"}},
                "no_outputs":       {"type": "boolean"},
                "max_output_lines": {"type": "integer"},
            },
            "required": ["path"],
        },
    }
]


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


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            name = request.get("name")
            params = request.get("parameters", {})
            if name == "extract_notebook":
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
