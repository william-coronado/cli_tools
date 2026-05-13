from __future__ import annotations
import json
import sys


TOOL_DEFINITIONS = [
    {
        "name": "git_file_context",
        "description": (
            "Get git context for a specific file: recent commits touching it, "
            "current diff vs. base branch, blame summary, and related files. "
            "Use before editing a file to understand its history."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file (absolute or relative to cwd).",
                },
                "base": {
                    "type": "string",
                    "description": "Base branch or commit for diff. Default: auto-detect.",
                },
                "commits": {
                    "type": "integer",
                    "description": "Number of recent commits to include. Default: 10.",
                },
                "no_blame": {
                    "type": "boolean",
                    "description": "Skip blame analysis. Faster for large files.",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "git_repo_context",
        "description": (
            "Get repo-level git context: branch status, uncommitted changes, "
            "and recent commit activity. Use at session start to orient yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Repo root path. Defaults to current directory.",
                },
                "commits": {
                    "type": "integer",
                    "description": "Number of recent commits to include. Default: 10.",
                },
            },
            "required": [],
        },
    },
]


def _handle_git_file_context(params: dict) -> str:
    from pathlib import Path
    from .context import GitContextExtractor
    from .renderer import Renderer

    file_path = params["file_path"]
    base = params.get("base")
    commits = params.get("commits", 10)

    target = Path(file_path).resolve()
    extractor = GitContextExtractor(
        repo_path=target.parent,
        max_commits=commits,
    )
    ctx = extractor.get_file_context(target, base=base)
    renderer = Renderer()
    return renderer.render_file_context(ctx, base=base or "")


def _handle_git_repo_context(params: dict) -> str:
    from pathlib import Path
    from .context import GitContextExtractor
    from .renderer import Renderer

    repo_path = params.get("repo_path", ".")
    commits = params.get("commits", 10)

    extractor = GitContextExtractor(
        repo_path=Path(repo_path).resolve(),
        max_commits=commits,
    )
    ctx = extractor.get_repo_context()
    renderer = Renderer()
    return renderer.render_repo_context(ctx)


def main() -> None:
    """MCP stdio server loop."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            name = request.get("name")
            params = request.get("parameters", {})

            if name == "git_file_context":
                result = _handle_git_file_context(params)
            elif name == "git_repo_context":
                result = _handle_git_repo_context(params)
            else:
                result = json.dumps({"error": f"Unknown tool: {name}"})

            response = {"result": result}
        except Exception as e:
            response = {"error": str(e)}

        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
