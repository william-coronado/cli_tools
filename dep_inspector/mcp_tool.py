from __future__ import annotations

import json
import sys


TOOL_DEFINITIONS = [
    {
        "name": "inspect_dependencies",
        "description": (
            "Inspect a project's dependency manifest and lockfile (Python or "
            "JavaScript). Returns declared/resolved/transitive summary, plus "
            "optional outdated and vulnerability checks. Use instead of reading "
            "raw lockfiles (which are routinely 500 KB+)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path":        {"type": "string"},
                "ecosystem":   {"type": "string", "enum": ["pypi", "npm"]},
                "outdated":    {"type": "boolean"},
                "audit":       {"type": "boolean"},
                "no_dev":      {"type": "boolean"},
                "direct_only": {"type": "boolean"},
                "severity":    {"type": "array", "items": {"type": "string"}},
            },
            "required": ["path"],
        },
    }
]


def _handle(params: dict) -> str:
    from .inspector import DepInspector, InspectorOptions

    opts = InspectorOptions(
        direct_only=bool(params.get("direct_only", False)),
        outdated=bool(params.get("outdated", False)),
        audit=bool(params.get("audit", False)),
        ecosystem=params.get("ecosystem"),
        include_dev=not bool(params.get("no_dev", False)),
        severity_filter=params.get("severity"),
    )
    result = DepInspector(opts).inspect(params["path"])
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
            if name == "inspect_dependencies":
                result = _handle(params)
            else:
                response = {"error": f"Unknown tool: {name}"}
                print(json.dumps(response), flush=True)
                continue
            response = {"result": result}
        except Exception as e:
            response = {"error": str(e)}
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
