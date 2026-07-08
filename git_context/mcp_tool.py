"""MCP handlers for git_context. Exposed via the unified server (mcp_server.py)."""
from __future__ import annotations


def _handle_git_file_context(params: dict) -> str:
    from pathlib import Path
    from .context import GitContextExtractor
    from .renderer import Renderer

    file_path = params["file_path"]
    base = params.get("base")
    commits = params.get("commits", 10)
    no_blame = bool(params.get("no_blame", False))

    target = Path(file_path).resolve()
    extractor = GitContextExtractor(
        repo_path=target.parent,
        max_commits=commits,
    )
    ctx = extractor.get_file_context(target, base=base, skip_blame=no_blame)
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
