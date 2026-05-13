from __future__ import annotations
import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m git_context.cli",
        description="Extract focused git context for a file or repository.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="File path (file mode) or directory (repo mode). Default: current directory.",
    )
    parser.add_argument("--output", "-o", default=None, help="Output file (default: stdout)")
    parser.add_argument(
        "--format", choices=["markdown", "json", "text"], default="markdown"
    )
    parser.add_argument("--base", default=None, help="Base branch/commit for diffs")
    parser.add_argument(
        "--commits", "-n", type=int, default=10, metavar="N",
        help="Number of recent commits to include (default: 10)"
    )
    parser.add_argument(
        "--diff-lines", type=int, default=200, metavar="N",
        help="Max diff lines to show (default: 200)"
    )
    parser.add_argument(
        "--context-lines", type=int, default=3, metavar="N",
        help="Lines of diff context (default: 3)"
    )
    parser.add_argument(
        "--blame-window", default="30d",
        help="Recency window for blame summary (default: 30d)"
    )
    parser.add_argument("--no-blame", action="store_true", help="Skip blame analysis")
    parser.add_argument("--no-diff", action="store_true", help="Skip diff output")
    parser.add_argument("--no-related", action="store_true", help="Skip related files analysis")
    parser.add_argument("--repo", action="store_true", help="Force repo mode")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print git commands to stderr")

    args = parser.parse_args(argv)

    target = Path(args.path).resolve()

    if not target.exists():
        print(f"error: path does not exist: {target}", file=sys.stderr)
        return 1

    repo_mode = args.repo or target.is_dir()

    from .context import GitContextExtractor
    from .renderer import Renderer
    from .git_runner import (
        GitBinaryNotFoundError,
        NotAGitRepoError,
        FileNotTrackedError,
        GitError,
    )

    try:
        extractor = GitContextExtractor(
            repo_path=target if repo_mode else target.parent,
            max_commits=args.commits,
            max_diff_lines=args.diff_lines,
            diff_context_lines=args.context_lines,
            blame_recent_window=args.blame_window,
            verbose=args.verbose,
        )

        renderer = Renderer()

        if repo_mode:
            ctx = extractor.get_repo_context()
            if args.format == "json":
                output = renderer.to_json(ctx)
            else:
                output = renderer.render_repo_context(ctx)
        else:
            ctx = extractor.get_file_context(target, base=args.base)
            if args.format == "json":
                output = renderer.to_json(ctx)
            else:
                output = renderer.render_file_context(ctx, base=args.base or "")

    except GitBinaryNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except NotAGitRepoError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except FileNotTrackedError as e:
        print(f"warning: {e}", file=sys.stderr)
        return 0
    except GitError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        if args.verbose:
            print(f"wrote {len(output)} chars to {args.output}", file=sys.stderr)
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
