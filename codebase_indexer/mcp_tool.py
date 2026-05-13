from __future__ import annotations
import json
import sys

TOOL_DEFINITIONS = [
    {
        "name": "index_codebase",
        "description": (
            "Walk a code repository and return a structured index of all files, "
            "classes, functions, and imports. Use this before reading individual files "
            "to understand repo structure without loading full file contents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the repository root. Defaults to cwd.",
                },
                "detail": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": "Index detail level. Use 'low' for large repos, 'high' for deep analysis.",
                },
                "format": {
                    "type": "string",
                    "enum": ["markdown", "json", "outline"],
                    "description": "Output format. Default: markdown.",
                },
                "include_extensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Limit indexing to these file extensions, e.g. [\".py\", \".ts\"]",
                },
                "exclude_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional glob patterns to exclude.",
                },
            },
            "required": [],
        },
    }
]


def _handle_index_codebase(params: dict) -> str:
    import json as _json
    from pathlib import Path
    from .indexer import CodebaseIndexer

    repo_path = params.get("repo_path", ".")
    detail = params.get("detail", "normal")
    fmt = params.get("format", "markdown")
    include_ext = params.get("include_extensions")
    excludes = params.get("exclude_patterns")

    indexer = CodebaseIndexer(
        root=Path(repo_path).resolve(),
        extra_excludes=excludes,
        include_extensions=include_ext,
        show_progress=False,
    )
    index = indexer.build()

    if fmt == "outline":
        return index.to_outline()
    if fmt == "json":
        return _json.dumps(index.to_json(), indent=2, default=str)
    return index.to_markdown(detail=detail)


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            name = request.get("name")
            params = request.get("parameters", {})
            if name == "index_codebase":
                result = _handle_index_codebase(params)
            else:
                result = json.dumps({"error": f"Unknown tool: {name}"})
            response = {"result": result}
        except Exception as exc:
            response = {"error": str(exc)}
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
