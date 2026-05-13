from __future__ import annotations

import json
import sys


TOOL_DEFINITIONS = [
    {
        "name": "summarize_log",
        "description": (
            "Summarize a log file, extracting only errors, warnings, tracebacks, and "
            "key metrics. Handles pytest output, Python logging, ML training logs, "
            "JSON logs, and web server logs. Returns compact markdown. Use instead of "
            "reading raw log files to save tokens."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to log file, directory, or '-' for stdin.",
                },
                "format_hint": {
                    "type": "string",
                    "enum": ["pytest", "python", "training", "json", "webserver", "generic"],
                    "description": "Override auto-detection if format is known.",
                },
                "errors_only": {
                    "type": "boolean",
                    "description": "Return only errors and tracebacks.",
                },
                "tail": {
                    "type": "integer",
                    "description": "Only process the last N lines.",
                },
            },
            "required": ["path"],
        },
    }
]


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


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            name = request.get("name")
            params = request.get("parameters", {})
            if name == "summarize_log":
                result = _handle(params)
            else:
                result = json.dumps({"error": f"Unknown tool: {name}"})
            response = {"result": result}
        except Exception as e:
            response = {"error": str(e)}
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
