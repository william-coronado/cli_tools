from __future__ import annotations

import json
import sys


TOOL_DEFINITIONS = [
    {
        "name": "summarize_data",
        "description": (
            "Summarize a tabular or structured data file (CSV, TSV, JSON, JSONL, "
            "Parquet, Excel, SQLite). Returns schema, sample rows (head + tail), "
            "and per-column statistics. Use instead of reading raw data files to "
            "save tokens."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to file."},
                "format_hint": {
                    "type": "string",
                    "enum": ["csv", "tsv", "json", "jsonl", "parquet", "xlsx", "sqlite"],
                },
                "table": {
                    "type": "string",
                    "description": "SQLite table or Excel sheet to restrict to.",
                },
                "sample": {
                    "type": "integer",
                    "description": "Head AND tail row count (default 5).",
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Limit to specific columns.",
                },
                "no_stats": {"type": "boolean"},
                "max_rows": {"type": "integer"},
            },
            "required": ["path"],
        },
    }
]


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


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            name = request.get("name")
            params = request.get("parameters", {})
            if name == "summarize_data":
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
